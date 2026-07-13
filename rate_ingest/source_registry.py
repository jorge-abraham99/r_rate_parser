from __future__ import annotations

from pathlib import Path

from rate_ingest.config import Settings
from rate_ingest.models import SourceDocument
from rate_ingest.utils import append_csv_rows, compute_checksum, copy_to_raw, read_csv_rows


SOURCE_REGISTRY_COLUMNS = [
    "id",
    "source_type",
    "file_name",
    "source_path",
    "provider_name",
    "received_at",
    "uploaded_by",
    "checksum",
    "status",
    "created_at",
]


def registry_path(settings: Settings) -> Path:
    return settings.registered_dir / "source_documents.csv"


def find_source_by_checksum(settings: Settings, checksum: str) -> dict[str, str] | None:
    for row in read_csv_rows(registry_path(settings)):
        if row.get("checksum") == checksum:
            return row
    return None


def register_source(settings: Settings, source_path: Path, uploaded_by: str | None = None) -> SourceDocument:
    settings.ensure()
    copied_path = copy_to_raw(source_path, settings.raw_dir)
    checksum = compute_checksum(copied_path)
    existing = find_source_by_checksum(settings, checksum)
    if existing:
        return SourceDocument(**deserialize_source_row(existing))

    source = SourceDocument(
        source_type=copied_path.suffix.replace(".", "").lower(),
        file_name=copied_path.name,
        source_path=str(copied_path),
        uploaded_by=uploaded_by,
        checksum=checksum,
        status="registered",
    )
    append_csv_rows(
        registry_path(settings),
        [{column: source.model_dump(mode="json").get(column) for column in SOURCE_REGISTRY_COLUMNS}],
    )
    return source


def deserialize_source_row(row: dict[str, str]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        normalized[key] = None if value == "" else value
    return normalized
