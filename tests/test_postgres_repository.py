from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import inspect
import sys
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.config import Settings
from rate_ingest.models import (
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
    SourceDocument,
)
from rate_ingest.repositories import (
    PostgresRateRepository,
    RateRepository,
    get_rate_repository,
)
from rate_ingest.repositories.postgres_mappings import (
    rate_card_from_db,
    rate_card_to_db,
    rate_charge_line_from_db,
    rate_charge_line_to_db,
    rate_import_from_db,
    rate_import_to_db,
    rate_note_from_db,
    rate_note_to_db,
    rate_offer_from_db,
    rate_offer_to_db,
    source_document_from_db,
    source_document_to_db,
)
from rate_ingest.repositories.postgres_repository import (
    secure_connection_string,
    validate_bundle,
)


ORGANIZATION_ID = UUID("123e4567-e89b-12d3-a456-426614174001")


def test_postgres_backend_requires_server_database_url(tmp_path: Path) -> None:
    settings = replace(
        Settings.load(cwd=tmp_path),
        rate_storage_backend="postgres",
        supabase_db_url=None,
    )

    with pytest.raises(RuntimeError, match="SUPABASE_DB_URL"):
        get_rate_repository(settings)


def test_postgres_connection_requires_ssl() -> None:
    secured = secure_connection_string(
        "postgresql://postgres:password@db.example.com:5432/postgres"
    )

    assert "sslmode=require" in secured
    assert "connect_timeout=5" in secured
    assert "application_name=rate_ingest" in secured

    with pytest.raises(ValueError, match="require SSL"):
        secure_connection_string(
            "postgresql://postgres:password@db.example.com:5432/postgres?sslmode=disable"
        )


def test_repository_operations_require_explicit_organization_id() -> None:
    for method_name in (
        "register_source_document",
        "add_import",
        "update_import",
        "get_import_record",
        "list_import_records",
        "load_import_bundle",
        "publish_import_bundle",
        "save_import_bundle",
        "approve_import",
        "reject_import",
        "remove_import_data",
        "load_approved_rate_library",
    ):
        parameter = inspect.signature(getattr(RateRepository, method_name)).parameters[
            "organization_id"
        ]
        assert parameter.default is inspect.Parameter.empty


def test_explicit_postgres_mappings_preserve_application_models() -> None:
    source = SourceDocument(
        id="src_mapping_test",
        source_type="xlsx",
        file_name="rates.xlsx",
        source_path="/tmp/rates.xlsx",
        provider_name="Test Provider",
        uploaded_by="operator@example.com",
        checksum="a" * 64,
    )
    rate_import = RateImport(
        id="import_mapping_test",
        source_document_id=source.id,
        parser_family="matrix",
        template_id="test_template",
        classification_confidence=0.95,
        status="approved",
        validation_summary_json={"errors": 0, "warnings": 1},
        approved_by="approver@example.com",
    )
    card = RateCard(
        id="card_mapping_test",
        rate_import_id=rate_import.id,
        provider_name="Test Provider",
        carrier_name="Test Carrier",
        document_type="ocean_export",
        commodity="General cargo",
        currency_default="USD",
        valid_from=date(2026, 8, 1),
        valid_to=date(2026, 8, 31),
        all_in_flag="unknown",
        notes_summary="Mapping note",
    )
    offer = RateOffer(
        id="offer_mapping_test",
        rate_card_id=card.id,
        offer_reference="QUOTE-1",
        commodity="General cargo",
        origin="Birmingham",
        place_of_receipt="Birmingham",
        pol="Felixstowe",
        pod="Singapore",
        final_destination="Singapore",
        zone="3",
        equipment_type="40HC",
        service_mode="SD / CY",
        transit_time_days=28,
        base_amount=1234.56,
        base_currency="USD",
        all_in_flag=False,
        routing_note="Direct",
        valid_from=date(2026, 8, 1),
        valid_to=date(2026, 8, 31),
        raw_sheet_name="Rates",
        raw_row_reference="Rates!D10",
        raw_row_json={"amount": "1234.56"},
    )
    charge = RateChargeLine(
        id="charge_mapping_test",
        rate_offer_id=offer.id,
        charge_name="Emergency Fuel Surcharge",
        charge_type="freight",
        basis="per_container",
        amount=20.15,
        currency="USD",
        included_flag="unknown",
        source_label="EFS",
        raw_value="USD 20.15",
    )
    note = RateNote(
        id="note_mapping_test",
        rate_card_id=card.id,
        rate_offer_id=offer.id,
        note_type="commercial",
        note_text="Test note",
        source_reference="Rates!A1",
    )
    source_database_id = uuid4()
    import_database_id = uuid4()
    card_database_id = uuid4()
    offer_database_id = uuid4()

    source_row = source_document_to_db(
        source,
        organization_id=ORGANIZATION_ID,
        database_id=source_database_id,
    )
    import_row = rate_import_to_db(
        rate_import,
        organization_id=ORGANIZATION_ID,
        database_id=import_database_id,
        source_document_database_id=source_database_id,
    )
    card_row = rate_card_to_db(
        card,
        organization_id=ORGANIZATION_ID,
        database_id=card_database_id,
        import_database_id=import_database_id,
    )
    offer_row = rate_offer_to_db(
        offer,
        organization_id=ORGANIZATION_ID,
        database_id=offer_database_id,
        import_database_id=import_database_id,
        card_database_id=card_database_id,
    )
    charge_row = rate_charge_line_to_db(
        charge,
        organization_id=ORGANIZATION_ID,
        database_id=uuid4(),
        card_database_id=card_database_id,
        offer_database_id=offer_database_id,
    )
    note_row = rate_note_to_db(
        note,
        organization_id=ORGANIZATION_ID,
        database_id=uuid4(),
        card_database_id=card_database_id,
        offer_database_id=offer_database_id,
    )

    assert offer_row["base_amount"] == Decimal("1234.56")
    assert charge_row["amount"] == Decimal("20.15")
    assert source_document_from_db(source_row) == source
    assert (
        rate_import_from_db(
            {
                **import_row,
                "source_application_id": source.id,
            }
        )
        == rate_import
    )
    assert (
        rate_card_from_db(
            {
                **card_row,
                "import_application_id": rate_import.id,
            }
        )
        == card
    )
    assert (
        rate_offer_from_db(
            {
                **offer_row,
                "card_application_id": card.id,
            }
        )
        == offer
    )
    assert (
        rate_charge_line_from_db(
            {
                **charge_row,
                "offer_application_id": offer.id,
            }
        )
        == charge
    )
    assert (
        rate_note_from_db(
            {
                **note_row,
                "card_application_id": card.id,
                "offer_application_id": offer.id,
            }
        )
        == note
    )

    date_metadata_row = rate_offer_to_db(
        offer.model_copy(update={"raw_row_json": {"sheet_date": date(2026, 8, 1)}}),
        organization_id=ORGANIZATION_ID,
        database_id=uuid4(),
        import_database_id=import_database_id,
        card_database_id=card_database_id,
    )
    assert date_metadata_row["metadata"]["raw_row_json"]["sheet_date"] == "2026-08-01"


def test_postgres_bundle_validation_rejects_cross_bundle_references() -> None:
    card = RateCard(
        id="card_bundle_test",
        rate_import_id="import_bundle_test",
        document_type="ocean_export",
    )
    offer = RateOffer(
        id="offer_bundle_test",
        rate_card_id="card_outside_bundle",
        equipment_type="40HC",
    )

    with pytest.raises(ValueError, match="unknown rate card"):
        validate_bundle([card], [offer], [], [])


def test_postgres_repository_can_receive_an_injected_pool(tmp_path: Path) -> None:
    pool = Mock()
    repository = PostgresRateRepository(Settings.load(cwd=tmp_path), pool=pool)

    assert repository.backend_name == "postgres"


def test_postgres_child_rows_use_one_batched_call_per_entity_type() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    payloads = [
        {"application_id": "one", "metadata": {}},
        {"application_id": "two", "metadata": {}},
    ]

    for insert_rows in (
        PostgresRateRepository._insert_cards,
        PostgresRateRepository._insert_offers,
        PostgresRateRepository._insert_charges,
        PostgresRateRepository._insert_notes,
    ):
        insert_rows(connection, payloads)

    assert cursor.executemany.call_count == 4
    assert all(len(call.args[1]) == 2 for call in cursor.executemany.call_args_list)


def test_application_id_migration_covers_all_persisted_entities() -> None:
    migration = Path(
        "supabase/migrations/20260808150650_add_application_ids.sql"
    ).read_text(encoding="utf-8")

    for table_name in (
        "source_documents",
        "rate_imports",
        "rate_cards",
        "rate_offers",
        "rate_charge_lines",
        "rate_notes",
    ):
        assert f"alter table public.{table_name}" in migration
        assert f"{table_name}_org_application_id_key" in migration
