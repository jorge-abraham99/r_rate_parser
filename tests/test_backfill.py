from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from rate_ingest.backfill import backfill_csv_to_postgres
from rate_ingest.config import Settings
from rate_ingest.models import RateCard, RateImport, RateOffer, SourceDocument
from rate_ingest.repositories import ImportBundle


ORGANIZATION_ID = UUID("123e4567-e89b-12d3-a456-426614174001")


class CsvFixtureRepository:
    def __init__(self, bundle: ImportBundle) -> None:
        self.bundle = bundle

    def list_import_records(self, *, organization_id):
        del organization_id
        return (self.bundle.rate_import,)

    def load_import_bundle(self, import_id, *, organization_id):
        del organization_id
        return self.bundle if import_id == self.bundle.rate_import.id else None


class CapturingPostgresRepository:
    def __init__(self) -> None:
        self.registered = []
        self.saved = []

    def register_source_document(self, source_path, *, organization_id, uploaded_by=None):
        self.registered.append((source_path, organization_id, uploaded_by))
        return SourceDocument(
            id="src_postgres",
            source_type=source_path.suffix.removeprefix("."),
            file_name=source_path.name,
            source_path=str(source_path),
            uploaded_by=uploaded_by,
            checksum="b" * 64,
        )

    def save_import_bundle(self, rate_import, cards, offers, charges, notes, canonical_rates, *, organization_id):
        self.saved.append(
            (rate_import, cards, offers, charges, notes, canonical_rates, organization_id)
        )


def csv_bundle(tmp_path: Path) -> ImportBundle:
    source_path = tmp_path / "rates.xlsx"
    source_path.write_bytes(b"fixture")
    source = SourceDocument(
        id="src_csv",
        source_type="xlsx",
        file_name=source_path.name,
        source_path=str(source_path),
        checksum="a" * 64,
    )
    rate_import = RateImport(
        id="import_csv",
        source_document_id=source.id,
        parser_family="matrix",
        status="approved",
    )
    card = RateCard(
        id="card_csv",
        rate_import_id=rate_import.id,
        document_type="ocean_export",
    )
    offer = RateOffer(
        id="offer_csv",
        rate_card_id=card.id,
        equipment_type="40HC",
    )
    return ImportBundle(source, rate_import, (card,), (offer,), (), ())


def test_csv_backfill_dry_run_validates_all_bundles(tmp_path: Path) -> None:
    bundle = csv_bundle(tmp_path)

    report = backfill_csv_to_postgres(
        Settings.load(cwd=tmp_path),
        ORGANIZATION_ID,
        source_repository=CsvFixtureRepository(bundle),
    )

    assert report.import_count == 1
    assert report.rate_card_count == 1
    assert report.rate_offer_count == 1
    assert report.applied is False


def test_csv_backfill_copies_bundle_with_postgres_source_id(tmp_path: Path) -> None:
    bundle = csv_bundle(tmp_path)
    target = CapturingPostgresRepository()

    report = backfill_csv_to_postgres(
        Settings.load(cwd=tmp_path),
        ORGANIZATION_ID,
        apply=True,
        source_repository=CsvFixtureRepository(bundle),
        target_repository=target,
    )

    assert report.applied is True
    assert target.registered[0][1] == ORGANIZATION_ID
    saved_import, cards, offers, charges, notes, canonical_rates, saved_organization = target.saved[0]
    assert saved_import.source_document_id == "src_postgres"
    assert cards == [bundle.cards[0]]
    assert offers == [bundle.offers[0]]
    assert charges == []
    assert notes == []
    assert canonical_rates == []
    assert saved_organization == ORGANIZATION_ID


def test_csv_backfill_refuses_partial_copy_when_source_is_missing(tmp_path: Path) -> None:
    bundle = csv_bundle(tmp_path)
    Path(bundle.source.source_path).unlink()
    target = CapturingPostgresRepository()

    with pytest.raises(ValueError, match="source file is missing"):
        backfill_csv_to_postgres(
            Settings.load(cwd=tmp_path),
            ORGANIZATION_ID,
            apply=True,
            source_repository=CsvFixtureRepository(bundle),
            target_repository=target,
        )

    assert target.registered == []
