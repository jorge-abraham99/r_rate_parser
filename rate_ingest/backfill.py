"""One-off, idempotent CSV-to-Postgres migration for the trial cutover."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from rate_ingest.config import Settings
from rate_ingest.repositories import (
    LOCAL_CSV_ORGANIZATION_ID,
    CsvRateRepository,
    PostgresRateRepository,
    RateRepository,
)


@dataclass(frozen=True)
class CsvBackfillReport:
    import_count: int
    rate_card_count: int
    rate_offer_count: int
    charge_line_count: int
    note_count: int
    applied: bool


def backfill_csv_to_postgres(
    settings: Settings,
    organization_id: UUID,
    *,
    apply: bool = False,
    source_repository: RateRepository | None = None,
    target_repository: RateRepository | None = None,
) -> CsvBackfillReport:
    """Copy every CSV import bundle into one Postgres organization.

    The dry run checks every source file and run bundle without opening a database
    connection. Applied runs are safe to retry: imports retain their application
    IDs and the Postgres bundle writer upserts each import before replacing its
    structured children.
    """

    csv_settings = replace(settings, rate_storage_backend="csv")
    source = source_repository or CsvRateRepository(csv_settings)
    imports = source.list_import_records(organization_id=LOCAL_CSV_ORGANIZATION_ID)
    bundles = []
    missing: list[str] = []
    for rate_import in imports:
        bundle = source.load_import_bundle(
            rate_import.id,
            organization_id=LOCAL_CSV_ORGANIZATION_ID,
        )
        if bundle is None:
            missing.append(f"{rate_import.id} (structured run bundle is missing)")
            continue
        if not Path(bundle.source.source_path).is_file():
            missing.append(f"{rate_import.id} (source file is missing)")
            continue
        bundles.append(bundle)

    if missing:
        raise ValueError(
            "CSV backfill cannot start until every import is recoverable: "
            + "; ".join(missing)
        )

    report = CsvBackfillReport(
        import_count=len(bundles),
        rate_card_count=sum(len(bundle.cards) for bundle in bundles),
        rate_offer_count=sum(len(bundle.offers) for bundle in bundles),
        charge_line_count=sum(len(bundle.charges) for bundle in bundles),
        note_count=sum(len(bundle.notes) for bundle in bundles),
        applied=apply,
    )
    if not apply:
        return report

    owns_target = target_repository is None
    target = target_repository or PostgresRateRepository(
        replace(settings, rate_storage_backend="postgres")
    )
    try:
        for bundle in bundles:
            postgres_source = target.register_source_document(
                Path(bundle.source.source_path),
                organization_id=organization_id,
                uploaded_by=bundle.source.uploaded_by,
                original_file_name=bundle.source.file_name,
            )
            postgres_import = bundle.rate_import.model_copy(
                update={"source_document_id": postgres_source.id}
            )
            target.save_import_bundle(
                postgres_import,
                list(bundle.cards),
                list(bundle.offers),
                list(bundle.charges),
                list(bundle.notes),
                [],
                organization_id=organization_id,
            )
    finally:
        if owns_target:
            target.close()

    return report
