from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.config import Settings
from rate_ingest.models import (
    CanonicalRate,
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
)
from rate_ingest.repositories import (
    LOCAL_CSV_ORGANIZATION_ID,
    ApprovedRateLibrary,
    CsvRateRepository,
    RateRepository,
    get_rate_repository,
)
from rate_ingest.services import search_approved_offers
from rate_ingest.utils import write_json


def test_rate_storage_backend_defaults_to_csv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RATE_STORAGE_BACKEND", raising=False)

    settings = Settings.load(cwd=tmp_path)

    assert settings.rate_storage_backend == "csv"
    assert isinstance(get_rate_repository(settings), CsvRateRepository)


def test_invalid_rate_storage_backend_fails_at_startup(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RATE_STORAGE_BACKEND", "sqlite")

    with pytest.raises(ValueError, match="csv or postgres"):
        Settings.load(cwd=tmp_path)


def test_csv_repository_preserves_entities_and_source_metadata(tmp_path: Path) -> None:
    settings = replace(Settings.load(cwd=tmp_path), rate_storage_backend="csv")
    settings.ensure()
    repository = CsvRateRepository(settings)
    incoming = tmp_path / "sample.csv"
    incoming.write_text(
        "origin,destination,amount\nLondon,Singapore,100\n", encoding="utf-8"
    )

    source = repository.register_source_document(
        incoming,
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
        uploaded_by="operator@example.com",
    )
    duplicate = repository.register_source_document(
        incoming,
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
        uploaded_by="other@example.com",
    )
    rate_import = RateImport(
        id="import_repository_test",
        source_document_id=source.id,
        parser_family="matrix",
        template_id="test_template",
        classification_confidence=0.95,
        status="pending_review",
        validation_summary_json={"errors": 0, "warnings": 1},
    )
    card = RateCard(
        id="card_repository_test",
        rate_import_id=rate_import.id,
        provider_name="Test Carrier",
        carrier_name="Test Carrier",
        document_type="ocean_export",
        currency_default="USD",
    )
    offer = RateOffer(
        id="offer_repository_test",
        rate_card_id=card.id,
        place_of_receipt="London",
        pod="Singapore",
        equipment_type="40HC",
        base_amount=100,
        base_currency="USD",
    )
    charge = RateChargeLine(
        id="charge_repository_test",
        rate_offer_id=offer.id,
        charge_name="Emergency Fuel Surcharge",
        charge_type="freight",
        basis="Container",
        amount=20,
        currency="USD",
    )
    note = RateNote(
        id="note_repository_test",
        rate_card_id=card.id,
        rate_offer_id=offer.id,
        note_type="commercial",
        note_text="Test note",
    )
    canonical = CanonicalRate(
        rate_type="ocean",
        from_raw="London",
        to_raw="Singapore",
        amount=100,
        currency="USD",
    )

    assert duplicate.id == source.id
    repository.save_import_bundle(
        rate_import,
        [card],
        [offer],
        [charge],
        [note],
        [canonical],
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
    )
    write_json(
        settings.runs_dir / rate_import.id / "source_snapshot.json",
        {
            **source.model_dump(mode="json"),
            "operator_carrier_key": "test-carrier",
        },
    )
    assert (
        repository.load_approved_rate_library(
            organization_id=LOCAL_CSV_ORGANIZATION_ID,
        ).offers
        == ()
    )

    rate_import = repository.approve_import(
        rate_import,
        [card],
        [offer],
        [charge],
        [note],
        [canonical],
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
        carrier_key="test-carrier",
        approved_by="operator@example.com",
    )

    import_records = repository.list_import_records(
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
    )
    library = repository.load_approved_rate_library(
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
    )

    assert import_records[0].id == rate_import.id
    assert import_records[0].source_document_id == source.id
    assert import_records[0].status == "approved"
    assert import_records[0].carrier_key == "test-carrier"
    assert library.cards == (card,)
    assert library.offers == (offer,)
    assert library.charges == (charge,)
    assert library.notes == (note,)
    assert (
        library.source_by_import[rate_import.id]["operator_carrier_key"]
        == "test-carrier"
    )

    rate_import.status = "archived"
    repository.update_import(
        rate_import,
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
    )

    assert (
        repository.list_import_records(
            organization_id=LOCAL_CSV_ORGANIZATION_ID,
        )[0].status
        == "archived"
    )

    repository.remove_import_data(
        rate_import.id,
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
        remove_import_record=True,
    )

    assert (
        repository.list_import_records(
            organization_id=LOCAL_CSV_ORGANIZATION_ID,
        )
        == ()
    )
    assert (
        repository.load_approved_rate_library(
            organization_id=LOCAL_CSV_ORGANIZATION_ID,
        ).offers
        == ()
    )


def test_search_service_uses_injected_repository(tmp_path: Path) -> None:
    settings = Settings.load(cwd=tmp_path)
    card = RateCard(
        id="card_service_test",
        rate_import_id="import_service_test",
        provider_name="Test Provider",
        carrier_name="Test Carrier",
        document_type="ocean_export",
        currency_default="USD",
    )
    offer = RateOffer(
        id="offer_service_test",
        rate_card_id=card.id,
        pol="Felixstowe",
        pod="Singapore",
        equipment_type="40HC",
        base_amount=500,
        base_currency="USD",
    )
    repository = Mock(spec=RateRepository)
    repository.load_approved_rate_library.return_value = ApprovedRateLibrary(
        cards=(card,),
        offers=(offer,),
        charges=(),
        notes=(),
        source_by_import={},
    )

    rows = search_approved_offers(
        settings,
        pod="Singapore",
        repository=repository,
    )

    repository.load_approved_rate_library.assert_called_once_with(
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
    )
    assert [row["offer_id"] for row in rows] == [offer.id]


def test_service_entry_points_do_not_bypass_rate_repository() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "rate_ingest/services.py",
        "rate_ingest/approve.py",
        "rate_ingest/search.py",
        "rate_ingest/cli.py",
    ):
        source = root.joinpath(relative_path).read_text(encoding="utf-8")
        assert "rate_ingest.warehouse" not in source
        assert "rate_ingest.source_registry" not in source
