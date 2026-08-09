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
        rate_import.status = "approved"
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

        repository.add_import(rate_import, organization_id=organization_a)
        repository.publish_import_bundle(
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
        library_a = repository.load_approved_rate_library(
            organization_id=organization_a,
        )
        library_b = repository.load_approved_rate_library(
            organization_id=organization_b,
        )

        assert stored_import is not None
        assert stored_import.id == rate_import.id
        assert stored_import.source_document_id == source_a.id
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
