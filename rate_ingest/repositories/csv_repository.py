from __future__ import annotations

import json
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
from rate_ingest.repositories.base import ApprovedRateLibrary, OrganizationId, RateRepository
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
            RateCard(**_deserialize_row(row))
            for row in read_csv_rows(paths["cards"])
        )
        offers = tuple(
            RateOffer(**_deserialize_row(row))
            for row in read_csv_rows(paths["offers"])
        )
        charges = tuple(
            RateChargeLine(**_deserialize_row(row))
            for row in read_csv_rows(paths["charges"])
        )
        notes = tuple(
            RateNote(**_deserialize_row(row))
            for row in read_csv_rows(paths["notes"])
        )
        source_by_import: dict[str, dict[str, Any]] = {}
        for card in cards:
            source_path = (
                self.settings.runs_dir
                / card.rate_import_id
                / "source_snapshot.json"
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
