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
from rate_ingest.repositories.base import ApprovedRateLibrary, RateRepository
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
        uploaded_by: str | None = None,
    ) -> SourceDocument:
        return register_source(self.settings, source_path, uploaded_by=uploaded_by)

    def add_import(self, rate_import: RateImport) -> None:
        record_import(self.settings, rate_import)

    def update_import(self, rate_import: RateImport) -> None:
        replace_import(self.settings, rate_import)

    def list_import_records(self) -> tuple[RateImport, ...]:
        rows = read_csv_rows(warehouse_paths(self.settings)["imports"])
        return tuple(RateImport(**_deserialize_row(row)) for row in rows)

    def publish_import_bundle(
        self,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
    ) -> None:
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
        remove_import_record: bool = False,
    ) -> None:
        remove_import_rows(
            self.settings,
            import_id,
            remove_import_record=remove_import_record,
        )

    def load_approved_rate_library(self) -> ApprovedRateLibrary:
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
