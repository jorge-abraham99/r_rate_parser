import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.locations import (
    LocationCatalogue,
    apply_location_catalogue,
    location_match_key,
)
from rate_ingest.config import Settings
from rate_ingest.models import RateCard, RateOffer
from rate_ingest.repositories.base import ApprovedRateLibrary, RateRepository
from rate_ingest.repositories.postgres_mappings import (
    rate_offer_from_db,
    rate_offer_to_db,
)
from rate_ingest.validate import validate_import
from rate_ingest.services import backfill_location_catalogue


def make_offer(**updates) -> RateOffer:
    payload = {
        "rate_card_id": "card_1",
        "origin": "Norwich",
        "place_of_receipt": "Norwich",
        "pol": "London Gateway",
        "pod": "Vung Tau",
        "final_destination": "Vung Tau",
        "equipment_type": "40HC",
        "base_amount": 100,
        "base_currency": "USD",
        "raw_sheet_name": "Rates",
        "raw_row_reference": "Rates!R12C4",
    }
    payload.update(updates)
    return RateOffer(**payload)


def test_catalogue_maps_agreed_destination_aliases_and_county_exceptions():
    catalogue = LocationCatalogue.default()

    assert catalogue.resolve("Lat Krabang").location.display_name == "Bangkok, TH"
    assert (
        catalogue.resolve("Cat Lei Terminal").location.display_name
        == "Ho Chi Minh, VN"
    )
    assert (
        catalogue.resolve("Water Orton Warwickshire, GB").location.display_name
        == "Water Orton, GB"
    )
    assert (
        catalogue.resolve("Rushden Hertfordshire, GB").location.display_name
        == "Rushden, Hertfordshire, GB"
    )
    assert (
        catalogue.resolve("Rushden Northampton, GB").location.display_name
        == "Rushden, Northamptonshire, GB"
    )
    assert catalogue.resolve("DA-NANG").location.display_name == "Da Nang, VN"
    assert catalogue.resolve("HAIPHONG").location.display_name == "Hai Phong, VN"
    assert catalogue.resolve("MANILA").location.display_name == "Manila, PH"
    assert catalogue.resolve("INDONESIA").location.display_name == "Indonesia, ID"


def test_catalogue_matching_ignores_case_and_spacing_but_not_punctuation():
    catalogue = LocationCatalogue.default()

    assert location_match_key("  LAT   KRABANG ") == location_match_key("lat krabang")
    assert catalogue.resolve("  LAT   KRABANG ") is not None
    assert catalogue.resolve("Lat-Krabang") is None


def test_source_location_code_takes_precedence_for_short_name():
    resolution = LocationCatalogue.default().resolve(
        "Newton",
        source_code="GBNWO",
    )

    assert resolution is not None
    assert resolution.matched_by == "source_code"
    assert resolution.location.display_name == "Newton, GB"


def test_offer_gets_canonical_links_without_changing_raw_carrier_fields():
    offer = make_offer()

    issues = apply_location_catalogue([offer], LocationCatalogue.default())

    assert issues == []
    assert offer.collection_location_code == "norwich-gb"
    assert offer.collection_location_name == "Norwich, GB"
    assert offer.destination_location_code == "vung-tau-vn"
    assert offer.destination_location_name == "Vung Tau, VN"
    assert offer.place_of_receipt == "Norwich"
    assert offer.origin == "Norwich"
    assert offer.pod == "Vung Tau"
    assert offer.final_destination == "Vung Tau"


def test_structured_msc_collection_row_creates_canonical_location():
    offer = make_offer(
        origin="Alford, Grampian Region",
        place_of_receipt="Alford, Grampian Region",
        service_mode="SD / CY",
        raw_row_json={
            "city": "Alford",
            "area": "Scottish Highlands",
            "county": "Grampian Region",
            "haulage_pol_raw": "Greenock",
            "zone": "ZONE 4",
            "haulage_row_reference": "Haulage Zones SEP!R12",
        },
    )

    issues = apply_location_catalogue([offer], LocationCatalogue.default())

    assert issues == []
    assert offer.collection_location_code == "alford-grampian-region-gb"
    assert offer.collection_location_name == "Alford, Grampian Region, GB"
    assert offer.place_of_receipt == "Alford, Grampian Region"


def test_unknown_location_blocks_publication_and_names_file_sheet_and_row():
    card = RateCard(
        id="card_1",
        rate_import_id="import_1",
        document_type="ocean_export",
    )
    offer = make_offer(place_of_receipt="Mystery Place", origin="Mystery Place")
    issues = apply_location_catalogue([offer], LocationCatalogue.default())

    report = validate_import(
        "import_1",
        card,
        [offer],
        [],
        location_issues=issues,
        source_file_name="carrier.xlsx",
    )

    location_error = next(
        item for item in report.items if item.rule_id == "unknown_collection_location"
    )
    assert location_error.severity == "ERROR"
    assert "Mystery Place" in location_error.message
    assert "carrier.xlsx" in location_error.message
    assert "Rates!R12C4" in location_error.message


def test_postgres_mapping_keeps_raw_fields_and_canonical_codes_and_names():
    offer = make_offer(
        collection_location_code="norwich-gb",
        collection_location_name="Norwich, GB",
        destination_location_code="vung-tau-vn",
        destination_location_name="Vung Tau, VN",
    )
    payload = rate_offer_to_db(
        offer,
        organization_id="00000000-0000-0000-0000-000000000001",
        database_id="00000000-0000-0000-0000-000000000002",
        import_database_id="00000000-0000-0000-0000-000000000003",
        card_database_id="00000000-0000-0000-0000-000000000004",
    )

    assert payload["collection"] == "Norwich"
    assert payload["destination"] == "Vung Tau"
    assert payload["collection_location_code"] == "norwich-gb"
    assert payload["destination_location_code"] == "vung-tau-vn"
    assert payload["metadata"]["collection_location_name"] == "Norwich, GB"
    assert payload["metadata"]["destination_location_name"] == "Vung Tau, VN"

    row = {
        **payload,
        "card_application_id": offer.rate_card_id,
        "application_id": offer.id,
    }
    restored = rate_offer_from_db(row)
    assert restored.place_of_receipt == "Norwich"
    assert restored.final_destination == "Vung Tau"
    assert restored.collection_location_name == "Norwich, GB"
    assert restored.destination_location_name == "Vung Tau, VN"


def test_existing_approved_offers_can_be_backfilled_without_reupload(tmp_path):
    offer = make_offer()
    repository = Mock(spec=RateRepository)
    repository.backend_name = "csv"
    repository.load_approved_rate_library.return_value = ApprovedRateLibrary(
        cards=(),
        offers=(offer,),
        charges=(),
        notes=(),
        source_by_import={},
    )
    settings = Settings.load(tmp_path)

    dry_run = backfill_location_catalogue(
        settings,
        repository=repository,
        organization_id="local-csv",
    )
    applied = backfill_location_catalogue(
        settings,
        apply=True,
        repository=repository,
        organization_id="local-csv",
    )

    assert dry_run == {
        "applied": False,
        "import_id": None,
        "offer_count": 1,
        "resolved_offer_count": 1,
        "unresolved_count": 0,
        "unresolved": [],
    }
    assert applied["applied"] is True
    repository.persist_offer_locations.assert_called_once()


def test_location_backfill_can_be_scoped_to_one_approved_import(tmp_path):
    target_card = RateCard(
        id="target_card",
        rate_import_id="target_import",
        document_type="ocean_export",
    )
    other_card = RateCard(
        id="other_card",
        rate_import_id="other_import",
        document_type="ocean_export",
    )
    target_offer = make_offer(
        rate_card_id=target_card.id,
        origin="Abercarn",
        place_of_receipt="Abercarn",
        service_mode="SD / CY",
        raw_row_json={
            "city": "Abercarn",
            "area": "South Wales",
            "county": "Caerphilly",
            "haulage_pol_raw": "Bristol",
            "zone": "ZONE 4",
            "haulage_row_reference": "Haulage Zones SEP!R2",
        },
    )
    other_offer = make_offer(
        rate_card_id=other_card.id,
        origin="Mystery Place",
        place_of_receipt="Mystery Place",
    )
    repository = Mock(spec=RateRepository)
    repository.backend_name = "csv"
    repository.load_approved_rate_library.return_value = ApprovedRateLibrary(
        cards=(target_card, other_card),
        offers=(target_offer, other_offer),
        charges=(),
        notes=(),
        source_by_import={},
    )

    result = backfill_location_catalogue(
        Settings.load(tmp_path),
        apply=True,
        import_id="target_import",
        repository=repository,
        organization_id="local-csv",
    )

    assert result == {
        "applied": True,
        "import_id": "target_import",
        "offer_count": 1,
        "resolved_offer_count": 1,
        "unresolved_count": 0,
        "unresolved": [],
    }
    persisted_offers = repository.persist_offer_locations.call_args.args[0]
    assert [offer.id for offer in persisted_offers] == [target_offer.id]
