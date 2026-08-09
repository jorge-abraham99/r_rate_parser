from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rate_ingest.config import Settings
from rate_ingest.models import (
    CanonicalRate,
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
    SourceDocument,
)
from rate_ingest.repositories.base import (
    ApprovedRateLibrary,
    OrganizationId,
    RateRepository,
)
from rate_ingest.source_registry import register_source
from rate_ingest.utils import read_csv_rows, read_json
from rate_ingest.warehouse import (
    publish_approved_rows,
    record_import,
    remove_import_rows,
    replace_import,
    warehouse_paths,
)


class CsvRateRepository(RateRepository):
    """Adapter for the existing CSV/JSON filesystem persistence."""

    backend_name = "csv"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def register_source_document(
        self,
        source_path: Path,
        *,
        organization_id: OrganizationId,
        uploaded_by: str | None = None,
    ) -> SourceDocument:
        del organization_id
        return register_source(self.settings, source_path, uploaded_by=uploaded_by)

    def add_import(
        self,
        rate_import: RateImport,
        *,
        organization_id: OrganizationId,
    ) -> None:
        del organization_id
        record_import(self.settings, rate_import)

    def update_import(
        self,
        rate_import: RateImport,
        *,
        organization_id: OrganizationId,
    ) -> None:
        del organization_id
        replace_import(self.settings, rate_import)

    def get_import_record(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
    ) -> RateImport | None:
        return next(
            (
                item
                for item in self.list_import_records(organization_id=organization_id)
                if item.id == import_id
            ),
            None,
        )

    def list_import_records(
        self,
        *,
        organization_id: OrganizationId,
    ) -> tuple[RateImport, ...]:
        del organization_id
        rows = read_csv_rows(warehouse_paths(self.settings)["imports"])
        return tuple(RateImport(**_deserialize_row(row)) for row in rows)

    def publish_import_bundle(
        self,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
        *,
        organization_id: OrganizationId,
    ) -> None:
        del organization_id
        publish_approved_rows(
            self.settings,
            cards,
            offers,
            charges,
            notes,
            canonical_rates,
        )

    def save_import_bundle(
        self,
        rate_import: RateImport,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
        *,
        organization_id: OrganizationId,
    ) -> None:
        del cards, offers, charges, notes, canonical_rates
        self.add_import(rate_import, organization_id=organization_id)

    def approve_import(
        self,
        rate_import: RateImport,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
        *,
        organization_id: OrganizationId,
        carrier_key: str | None,
        approved_by: str,
        approved_by_user_id: str | None = None,
    ) -> RateImport:
        del approved_by_user_id
        if rate_import.status != "pending_review":
            raise ValueError("Only a pending review import can be approved.")
        if rate_import.validation_summary_json.get("errors", 0):
            raise ValueError(
                "Import has blocking validation errors and cannot be approved."
            )

        now = datetime.now(timezone.utc)
        if carrier_key:
            for previous in self.list_import_records(organization_id=organization_id):
                if previous.id == rate_import.id or previous.status != "approved":
                    continue
                previous_key = previous.carrier_key
                if not previous_key:
                    snapshot_path = (
                        self.settings.runs_dir / previous.id / "source_snapshot.json"
                    )
                    if snapshot_path.exists():
                        previous_key = read_json(snapshot_path).get(
                            "operator_carrier_key"
                        )
                if previous_key != carrier_key:
                    continue
                remove_import_rows(self.settings, previous.id)
                previous.status = "archived"
                previous.archived_at = now
                replace_import(self.settings, previous)

        rate_import.status = "approved"
        rate_import.carrier_key = carrier_key
        rate_import.approved_by = approved_by
        rate_import.approved_at = now
        rate_import.rejected_by = None
        rate_import.rejected_at = None
        rate_import.rejection_reason = None
        rate_import.archived_at = None
        publish_approved_rows(
            self.settings,
            cards,
            offers,
            charges,
            notes,
            canonical_rates,
        )
        replace_import(self.settings, rate_import)
        return rate_import

    def reject_import(
        self,
        rate_import: RateImport,
        reason: str,
        *,
        organization_id: OrganizationId,
        rejected_by_user_id: str | None = None,
    ) -> RateImport:
        del organization_id
        if rate_import.status not in {"pending_review", "failed"}:
            raise ValueError("Only a pending or failed import can be rejected.")
        rate_import.status = "rejected"
        rate_import.rejected_at = datetime.now(timezone.utc)
        rate_import.rejected_by = rejected_by_user_id
        rate_import.rejection_reason = reason
        replace_import(self.settings, rate_import)
        return rate_import

    def remove_import_data(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
        remove_import_record: bool = False,
    ) -> None:
        del organization_id
        remove_import_rows(
            self.settings,
            import_id,
            remove_import_record=remove_import_record,
        )

    def load_approved_rate_library(
        self,
        *,
        organization_id: OrganizationId,
    ) -> ApprovedRateLibrary:
        del organization_id
        paths = warehouse_paths(self.settings)
        cards = tuple(
            RateCard(**_deserialize_row(row)) for row in read_csv_rows(paths["cards"])
        )
        offers = tuple(
            RateOffer(**_deserialize_row(row)) for row in read_csv_rows(paths["offers"])
        )
        charges = tuple(
            RateChargeLine(**_deserialize_row(row))
            for row in read_csv_rows(paths["charges"])
        )
        notes = tuple(
            RateNote(**_deserialize_row(row)) for row in read_csv_rows(paths["notes"])
        )
        source_by_import: dict[str, dict[str, Any]] = {}
        for card in cards:
            source_path = (
                self.settings.runs_dir / card.rate_import_id / "source_snapshot.json"
            )
            if source_path.exists():
                source_by_import[card.rate_import_id] = read_json(source_path)
        return ApprovedRateLibrary(
            cards=cards,
            offers=offers,
            charges=charges,
            notes=notes,
            source_by_import=source_by_import,
        )


def _deserialize_row(row: dict[str, str]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in row.items():
        if value == "":
            parsed[key] = None
            continue
        if key in {"base_amount", "amount", "classification_confidence"}:
            parsed[key] = float(value)
            continue
        if key.endswith("_json"):
            try:
                parsed[key] = json.loads(value)
            except json.JSONDecodeError:
                parsed[key] = {}
            continue
        parsed[key] = value
    return parsed
