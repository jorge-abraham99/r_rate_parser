from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_ingest.config import Settings
from rate_ingest.models import RateCard, RateChargeLine, RateImport, RateNote, RateOffer
from rate_ingest.repositories import PostgresRateRepository
from rate_ingest.repositories.postgres_repository import secure_connection_string
from rate_ingest.services import deserialize_row, import_source_file, load_run_payload


RUN_INTEGRATION = os.getenv("RUN_POSTGRES_INTEGRATION_TESTS", "").lower() == "true"
DATABASE_URL = os.getenv("SUPABASE_DB_URL")

PARSER_SAMPLES = (
    ("rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx", "tabular_lane"),
    ("rate_sheet_files/COSCO FAR-EAST RATES.xlsx", "matrix"),
    ("rate_sheet_files/MAERSK Q-1, INDIA AND FAR-EAST.xlsx", "offer_block"),
    ("rate_sheet_files/REUDAN_E1E_E3E_WAP_Q2 2026.xlsx", "site_to_site_rows"),
    (
        "rate_sheet_files/Export Waste Haulage Bristol + ALL other UK POLS INC GBLGP - GBTIL - Q2 2026 VALIDITY.xlsx",
        "haulage_matrix",
    ),
    ("RE_ Far East Wastepaper for April - Reudan.eml", "email_table"),
    ("rate_sheet_files/MSC - FAR EAST  AUGUST.xlsx", "msc_zoned_inline"),
    ("rate_sheet_files/HAPAG - FAR EAST RATES.xlsx", "hapag_door_matrix"),
    ("rate_sheet_files/Tuticorin.pdf", "cosco_pdf_quote"),
)


@pytest.mark.skipif(
    not RUN_INTEGRATION or not DATABASE_URL,
    reason="Set RUN_POSTGRES_INTEGRATION_TESTS=true and SUPABASE_DB_URL to run",
)
def test_real_hapag_bundle_round_trips_with_organization_isolation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    organization_a = uuid4()
    organization_b = uuid4()
    suffix = uuid4().hex[:12]
    connection_string = secure_connection_string(DATABASE_URL or "")
    settings = replace(
        Settings.load(cwd=tmp_path),
        supabase_db_url=DATABASE_URL,
        rate_storage_backend="postgres",
    )
    repository = PostgresRateRepository(settings)

    try:
        with psycopg.connect(
            connection_string,
            autocommit=True,
            prepare_threshold=None,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into public.organizations (id, name, slug)
                    values (%s, %s, %s)
                    """,
                    [
                        (
                            organization_a,
                            "Codex Stage 4 Test A",
                            f"codex-stage4-a-{suffix}",
                        ),
                        (
                            organization_b,
                            "Codex Stage 4 Test B",
                            f"codex-stage4-b-{suffix}",
                        ),
                    ],
                )

        source_path = Path("rate_sheet_files/HAPAG - FAR EAST RATES.xlsx")
        source_a = repository.register_source_document(
            source_path,
            organization_id=organization_a,
        )
        duplicate_a = repository.register_source_document(
            source_path,
            organization_id=organization_a,
        )
        source_b = repository.register_source_document(
            source_path,
            organization_id=organization_b,
        )

        assert duplicate_a.id == source_a.id
        assert source_b.id != source_a.id
        assert source_b.checksum == source_a.checksum

        csv_root = tmp_path / "csv_parse"
        monkeypatch.setenv("RATE_INGEST_ROOT", str(csv_root))
        csv_settings = replace(
            Settings.load(cwd=csv_root),
            rate_storage_backend="csv",
        )
        result = import_source_file(csv_settings, source_path)
        payload = load_run_payload(csv_settings.runs_dir / result["import_id"])
        rate_import = RateImport(**payload["rate_import"])
        rate_import.source_document_id = source_a.id
        cards = [RateCard(**deserialize_row(row)) for row in payload["rate_cards"]]
        offers = [RateOffer(**deserialize_row(row)) for row in payload["rate_offers"]]
        charges = [
            RateChargeLine(**deserialize_row(row))
            for row in payload["rate_charge_lines"]
        ]
        notes = [RateNote(**deserialize_row(row)) for row in payload["rate_notes"]]
        if not notes:
            notes.append(
                RateNote(
                    rate_card_id=cards[0].id,
                    note_type="integration_test",
                    note_text="Stage 4 disposable integration note",
                )
            )

        repository.save_import_bundle(
            rate_import,
            cards,
            offers,
            charges,
            notes,
            [],
            organization_id=organization_a,
        )

        stored_import = repository.get_import_record(
            rate_import.id,
            organization_id=organization_a,
        )
        pending_library = repository.load_approved_rate_library(
            organization_id=organization_a,
        )
        assert stored_import is not None
        assert stored_import.status == "pending_review"
        assert pending_library.cards == ()
        with psycopg.connect(
            connection_string,
            autocommit=True,
            prepare_threshold=None,
            row_factory=dict_row,
        ) as connection:
            pending_counts = connection.execute(
                """
                select
                  (select count(*) from public.rate_cards where organization_id = %s) as cards,
                  (select count(*) from public.rate_offers where organization_id = %s) as offers,
                  (select count(*) from public.rate_charge_lines where organization_id = %s) as charges,
                  (select count(*) from public.rate_notes where organization_id = %s) as notes
                """,
                (organization_a, organization_a, organization_a, organization_a),
            ).fetchone()
        assert pending_counts == {
            "cards": len(cards),
            "offers": len(offers),
            "charges": len(charges),
            "notes": len(notes),
        }

        approved = repository.approve_import(
            rate_import,
            cards,
            offers,
            charges,
            notes,
            [],
            organization_id=organization_a,
            carrier_key="hapag-stage5",
            approved_by="integration-test",
        )
        library_a = repository.load_approved_rate_library(
            organization_id=organization_a,
        )
        library_b = repository.load_approved_rate_library(
            organization_id=organization_b,
        )

        assert approved.status == "approved"
        assert approved.carrier_key == "hapag-stage5"
        assert approved.source_document_id == source_a.id
        assert len(library_a.cards) == len(cards)
        assert len(library_a.offers) == len(offers)
        assert len(library_a.charges) == len(charges)
        assert len(library_a.notes) == len(notes)
        assert library_a.cards[0].id == cards[0].id
        assert library_a.offers[0].equipment_type == offers[0].equipment_type
        assert library_a.charges[0].amount == charges[0].amount
        assert library_b.cards == ()
        assert (
            repository.get_import_record(
                rate_import.id,
                organization_id=organization_b,
            )
            is None
        )

        (
            replacement_import,
            replacement_cards,
            replacement_offers,
            replacement_charges,
            replacement_notes,
        ) = clone_bundle(
            rate_import,
            cards,
            offers,
            charges,
            notes,
        )
        repository.save_import_bundle(
            replacement_import,
            replacement_cards,
            replacement_offers,
            replacement_charges,
            replacement_notes,
            [],
            organization_id=organization_a,
        )
        repository.approve_import(
            replacement_import,
            replacement_cards,
            replacement_offers,
            replacement_charges,
            replacement_notes,
            [],
            organization_id=organization_a,
            carrier_key="hapag-stage5",
            approved_by="integration-test",
        )
        archived = repository.get_import_record(
            rate_import.id,
            organization_id=organization_a,
        )
        current = repository.get_import_record(
            replacement_import.id,
            organization_id=organization_a,
        )
        assert archived is not None and archived.status == "archived"
        assert archived.archived_at is not None
        assert current is not None and current.status == "approved"
        with psycopg.connect(
            connection_string,
            autocommit=True,
            prepare_threshold=None,
            row_factory=dict_row,
        ) as connection:
            historical_card_count = connection.execute(
                """
                select count(*) as count
                from public.rate_cards
                where organization_id = %s
                """,
                (organization_a,),
            ).fetchone()["count"]
        assert historical_card_count == len(cards) + len(replacement_cards)
        current_library = repository.load_approved_rate_library(
            organization_id=organization_a,
        )
        assert len(current_library.cards) == len(replacement_cards)

        (
            rejected_import,
            rejected_cards,
            rejected_offers,
            rejected_charges,
            rejected_notes,
        ) = clone_bundle(
            rate_import,
            cards,
            offers,
            charges,
            notes,
        )
        repository.save_import_bundle(
            rejected_import,
            rejected_cards,
            rejected_offers,
            rejected_charges,
            rejected_notes,
            [],
            organization_id=organization_a,
        )
        rejected = repository.reject_import(
            rejected_import,
            "Not commercially valid",
            organization_id=organization_a,
        )
        assert rejected.status == "rejected"
        assert rejected.rejected_at is not None
        assert rejected.rejection_reason == "Not commercially valid"
        repository.remove_import_data(
            rejected.id,
            organization_id=organization_a,
            remove_import_record=True,
        )
        assert (
            repository.get_import_record(
                rejected.id,
                organization_id=organization_a,
            )
            is None
        )
        with psycopg.connect(
            connection_string,
            autocommit=True,
            prepare_threshold=None,
            row_factory=dict_row,
        ) as connection:
            source_count = connection.execute(
                """
                select count(*) as count
                from public.source_documents
                where organization_id = %s and application_id = %s
                """,
                (organization_a, source_a.id),
            ).fetchone()["count"]
        assert source_count == 1
    finally:
        repository.close()
        with psycopg.connect(
            connection_string,
            autocommit=True,
            prepare_threshold=None,
        ) as connection:
            connection.execute(
                "delete from public.organizations where id = any(%s)",
                ([organization_a, organization_b],),
            )


def clone_bundle(rate_import, cards, offers, charges, notes):
    suffix = uuid4().hex[:12]
    cloned_import = rate_import.model_copy(
        update={
            "id": f"import_{suffix}",
            "status": "pending_review",
            "carrier_key": None,
            "approved_by": None,
            "approved_at": None,
            "archived_at": None,
        }
    )
    card_ids = {card.id: f"card_{uuid4().hex[:12]}" for card in cards}
    cloned_cards = [
        card.model_copy(
            update={
                "id": card_ids[card.id],
                "rate_import_id": cloned_import.id,
            }
        )
        for card in cards
    ]
    offer_ids = {offer.id: f"offer_{uuid4().hex[:12]}" for offer in offers}
    cloned_offers = [
        offer.model_copy(
            update={
                "id": offer_ids[offer.id],
                "rate_card_id": card_ids[offer.rate_card_id],
            }
        )
        for offer in offers
    ]
    cloned_charges = [
        charge.model_copy(
            update={
                "id": f"charge_{uuid4().hex[:12]}",
                "rate_offer_id": offer_ids[charge.rate_offer_id],
            }
        )
        for charge in charges
    ]
    cloned_notes = [
        note.model_copy(
            update={
                "id": f"note_{uuid4().hex[:12]}",
                "rate_card_id": card_ids[note.rate_card_id],
                "rate_offer_id": (
                    offer_ids[note.rate_offer_id]
                    if note.rate_offer_id is not None
                    else None
                ),
            }
        )
        for note in notes
    ]
    return (
        cloned_import,
        cloned_cards,
        cloned_offers,
        cloned_charges,
        cloned_notes,
    )


@pytest.mark.skipif(
    not RUN_INTEGRATION or not DATABASE_URL,
    reason="Set RUN_POSTGRES_INTEGRATION_TESTS=true and SUPABASE_DB_URL to run",
)
@pytest.mark.parametrize(("source_name", "parser_family"), PARSER_SAMPLES)
def test_real_parser_family_matches_csv_after_postgres_approval(
    tmp_path: Path,
    monkeypatch,
    source_name: str,
    parser_family: str,
) -> None:
    organization_id = uuid4()
    suffix = uuid4().hex[:12]
    connection_string = secure_connection_string(DATABASE_URL or "")
    settings = replace(
        Settings.load(cwd=tmp_path),
        supabase_db_url=DATABASE_URL,
        rate_storage_backend="postgres",
    )
    repository = PostgresRateRepository(settings)
    source_path = Path(source_name)

    try:
        with psycopg.connect(
            connection_string,
            autocommit=True,
            prepare_threshold=None,
        ) as connection:
            connection.execute(
                """
                insert into public.organizations (id, name, slug)
                values (%s, %s, %s)
                """,
                (
                    organization_id,
                    f"Codex Stage 5 {parser_family}",
                    f"codex-stage5-{suffix}",
                ),
            )

        stored_source = repository.register_source_document(
            source_path,
            organization_id=organization_id,
        )
        csv_root = tmp_path / "csv_parse"
        monkeypatch.setenv("RATE_INGEST_ROOT", str(csv_root))
        csv_settings = replace(
            Settings.load(cwd=csv_root),
            rate_storage_backend="csv",
        )
        result = import_source_file(csv_settings, source_path)
        payload = load_run_payload(csv_settings.runs_dir / result["import_id"])
        rate_import = RateImport(**payload["rate_import"])
        rate_import.source_document_id = stored_source.id
        cards = [RateCard(**deserialize_row(row)) for row in payload["rate_cards"]]
        offers = [RateOffer(**deserialize_row(row)) for row in payload["rate_offers"]]
        charges = [
            RateChargeLine(**deserialize_row(row))
            for row in payload["rate_charge_lines"]
        ]
        notes = [RateNote(**deserialize_row(row)) for row in payload["rate_notes"]]

        assert rate_import.parser_family == parser_family
        repository.save_import_bundle(
            rate_import,
            cards,
            offers,
            charges,
            notes,
            [],
            organization_id=organization_id,
        )
        pending = repository.get_import_record(
            rate_import.id,
            organization_id=organization_id,
        )
        assert pending is not None and pending.status == rate_import.status
        assert (
            repository.load_approved_rate_library(
                organization_id=organization_id,
            ).cards
            == ()
        )

        approved = repository.approve_import(
            rate_import,
            cards,
            offers,
            charges,
            notes,
            [],
            organization_id=organization_id,
            carrier_key=f"stage5-{parser_family}",
            approved_by="integration-test",
        )
        library = repository.load_approved_rate_library(
            organization_id=organization_id,
        )

        assert approved.status == "approved"
        assert approved.template_id == rate_import.template_id
        assert len(library.cards) == len(cards)
        assert len(library.offers) == len(offers)
        assert len(library.charges) == len(charges)
        assert len(library.notes) == len(notes)
        assert {card.id for card in library.cards} == {card.id for card in cards}
        assert {offer.id for offer in library.offers} == {offer.id for offer in offers}
        if offers:
            expected_offer = offers[0]
            stored_offer = next(
                item for item in library.offers if item.id == expected_offer.id
            )
            assert stored_offer == expected_offer
        if charges:
            expected_charge = charges[0]
            stored_charge = next(
                item for item in library.charges if item.id == expected_charge.id
            )
            assert stored_charge == expected_charge
        if notes:
            expected_note = notes[0]
            stored_note = next(
                item for item in library.notes if item.id == expected_note.id
            )
            assert stored_note == expected_note
    finally:
        repository.close()
        with psycopg.connect(
            connection_string,
            autocommit=True,
            prepare_threshold=None,
        ) as connection:
            connection.execute(
                "delete from public.organizations where id = %s",
                (organization_id,),
            )
