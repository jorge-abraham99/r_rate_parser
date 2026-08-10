from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4

from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

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
    ImportBundle,
    OrganizationId,
    RateRepository,
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
from rate_ingest.utils import compute_checksum, copy_to_raw


SOURCE_COLUMNS = """
    id, application_id, organization_id, original_filename, source_type,
    sha256, storage_path, uploaded_by, metadata, created_at
"""

IMPORT_COLUMNS = """
    i.id, i.application_id, i.organization_id, i.source_document_id,
    i.template_id, i.parser_family, i.match_confidence, i.status,
    i.carrier_key, i.validation_report, i.parse_summary,
    i.approved_at, i.approved_by, i.rejected_at, i.rejected_by,
    i.rejection_reason, i.archived_at,
    i.created_at, s.application_id as source_application_id
"""


class PostgresRateRepository(RateRepository):
    """Organization-scoped Supabase Postgres persistence adapter."""

    backend_name = "postgres"

    def __init__(self, settings: Settings, *, pool: Any | None = None) -> None:
        self.settings = settings
        if pool is not None:
            self._pool = pool
            return
        if not settings.supabase_db_url:
            raise RuntimeError(
                "SUPABASE_DB_URL is required when RATE_STORAGE_BACKEND=postgres"
            )
        self._pool = ConnectionPool(
            secure_connection_string(settings.supabase_db_url),
            min_size=0,
            max_size=5,
            max_idle=300,
            timeout=10,
            open=True,
            kwargs={
                "autocommit": False,
                "prepare_threshold": None,
                "row_factory": dict_row,
            },
        )

    def close(self) -> None:
        self._pool.close()

    def register_source_document(
        self,
        source_path: Path,
        *,
        organization_id: OrganizationId,
        uploaded_by: str | None = None,
        original_file_name: str | None = None,
    ) -> SourceDocument:
        organization_uuid = require_organization_uuid(organization_id)
        self.settings.ensure()
        copied_path = copy_to_raw(source_path, self.settings.raw_dir)
        checksum = compute_checksum(copied_path)
        source = SourceDocument(
            source_type=copied_path.suffix.replace(".", "").lower(),
            file_name=(
                Path(original_file_name).name
                if original_file_name
                else copied_path.name
            ),
            source_path=str(copied_path),
            uploaded_by=uploaded_by,
            checksum=checksum,
            status="registered",
        )
        payload = source_document_to_db(
            source,
            organization_id=organization_uuid,
            database_id=uuid4(),
        )
        with self._pool.connection() as connection:
            row = connection.execute(
                f"""
                insert into public.source_documents (
                    id, application_id, organization_id, original_filename,
                    source_type, sha256, storage_path, uploaded_by, metadata, created_at
                ) values (
                    %(id)s, %(application_id)s, %(organization_id)s,
                    %(original_filename)s, %(source_type)s, %(sha256)s,
                    %(storage_path)s, %(uploaded_by)s, %(metadata)s, %(created_at)s
                )
                on conflict (organization_id, sha256) do update
                set original_filename = excluded.original_filename
                returning {SOURCE_COLUMNS}
                """,
                {**payload, "metadata": Jsonb(payload["metadata"])},
            ).fetchone()
        return source_document_from_db(row)

    def add_import(
        self,
        rate_import: RateImport,
        *,
        organization_id: OrganizationId,
    ) -> None:
        organization_uuid = require_organization_uuid(organization_id)
        with self._pool.connection() as connection:
            self._upsert_import(connection, rate_import, organization_uuid)

    def update_import(
        self,
        rate_import: RateImport,
        *,
        organization_id: OrganizationId,
    ) -> None:
        self.add_import(rate_import, organization_id=organization_id)

    def get_import_record(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
    ) -> RateImport | None:
        organization_uuid = require_organization_uuid(organization_id)
        with self._pool.connection() as connection:
            row = connection.execute(
                f"""
                select {IMPORT_COLUMNS}
                from public.rate_imports i
                join public.source_documents s
                  on s.organization_id = i.organization_id
                 and s.id = i.source_document_id
                where i.organization_id = %s and i.application_id = %s
                """,
                (organization_uuid, import_id),
            ).fetchone()
        return rate_import_from_db(row) if row else None

    def list_import_records(
        self,
        *,
        organization_id: OrganizationId,
    ) -> tuple[RateImport, ...]:
        organization_uuid = require_organization_uuid(organization_id)
        with self._pool.connection() as connection:
            rows = connection.execute(
                f"""
                select {IMPORT_COLUMNS}
                from public.rate_imports i
                join public.source_documents s
                  on s.organization_id = i.organization_id
                 and s.id = i.source_document_id
                where i.organization_id = %s
                order by i.created_at
                """,
                (organization_uuid,),
            ).fetchall()
        return tuple(rate_import_from_db(row) for row in rows)

    def load_import_bundle(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
    ) -> ImportBundle | None:
        organization_uuid = require_organization_uuid(organization_id)
        with self._pool.connection() as connection:
            import_row = self._get_import_row(connection, import_id, organization_uuid)
            if import_row is None:
                return None
            import_database_id = import_row["id"]
            source_row = connection.execute(
                """
                select s.id, s.application_id, s.organization_id,
                       s.original_filename, s.source_type, s.sha256,
                       s.storage_path, s.uploaded_by, s.metadata, s.created_at
                from public.source_documents s
                join public.rate_imports i
                  on i.organization_id = s.organization_id
                 and i.source_document_id = s.id
                where i.organization_id = %s and i.id = %s
                """,
                (organization_uuid, import_database_id),
            ).fetchone()
            card_rows = connection.execute(
                """
                select c.id, c.application_id, c.provider, c.carrier,
                       c.commodity, c.currency, c.valid_from, c.valid_to,
                       c.is_all_in, c.document_type, c.metadata, c.created_at,
                       i.application_id as import_application_id
                from public.rate_cards c
                join public.rate_imports i
                  on i.organization_id = c.organization_id and i.id = c.import_id
                where c.organization_id = %s and c.import_id = %s
                order by c.created_at, c.application_id
                """,
                (organization_uuid, import_database_id),
            ).fetchall()
            offer_rows = connection.execute(
                """
                select o.id, o.application_id, o.collection, o.origin, o.pol,
                       o.pod, o.destination, o.equipment, o.service_mode,
                       o.base_amount, o.currency, o.routing, o.valid_from,
                       o.valid_to, o.source_reference, o.metadata, o.created_at,
                       c.application_id as card_application_id
                from public.rate_offers o
                join public.rate_cards c
                  on c.organization_id = o.organization_id and c.id = o.rate_card_id
                where o.organization_id = %s and o.import_id = %s
                order by o.created_at, o.application_id
                """,
                (organization_uuid, import_database_id),
            ).fetchall()
            offer_ids = [row["id"] for row in offer_rows]
            charge_rows = (
                connection.execute(
                    """
                    select ch.id, ch.application_id, ch.charge_name, ch.amount,
                           ch.currency, ch.basis, ch.charge_type, ch.is_included,
                           ch.source_reference, ch.metadata, ch.created_at,
                           ch.rate_offer_id
                    from public.rate_charge_lines ch
                    where ch.organization_id = %s
                      and ch.rate_offer_id = any(%s)
                    order by ch.created_at, ch.application_id
                    """,
                    (organization_uuid, offer_ids),
                ).fetchall()
                if offer_ids
                else []
            )
            note_rows = connection.execute(
                """
                select n.id, n.application_id, n.note_type, n.note_text,
                       n.source_reference, n.metadata, n.created_at,
                       c.application_id as card_application_id,
                       o.application_id as offer_application_id
                from public.rate_notes n
                join public.rate_cards c
                  on c.organization_id = n.organization_id and c.id = n.rate_card_id
                left join public.rate_offers o
                  on o.organization_id = n.organization_id and o.id = n.rate_offer_id
                where n.organization_id = %s and c.import_id = %s
                order by n.created_at, n.application_id
                """,
                (organization_uuid, import_database_id),
            ).fetchall()
        if source_row is None:
            raise RuntimeError(f"Source document missing for import {import_id}")
        offer_application_ids = {
            row["id"]: row["application_id"] for row in offer_rows
        }
        for row in charge_rows:
            row["offer_application_id"] = offer_application_ids[
                row["rate_offer_id"]
            ]
        return ImportBundle(
            source=source_document_from_db(source_row),
            rate_import=rate_import_from_db(import_row),
            cards=tuple(rate_card_from_db(row) for row in card_rows),
            offers=tuple(rate_offer_from_db(row) for row in offer_rows),
            charges=tuple(rate_charge_line_from_db(row) for row in charge_rows),
            notes=tuple(rate_note_from_db(row) for row in note_rows),
        )

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
        del canonical_rates
        organization_uuid = require_organization_uuid(organization_id)
        import_application_id = validate_bundle(cards, offers, charges, notes)
        if import_application_id is None:
            return

        with self._pool.connection() as connection:
            self._replace_import_bundle(
                connection,
                import_application_id,
                cards,
                offers,
                charges,
                notes,
                organization_uuid,
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
        del canonical_rates
        organization_uuid = require_organization_uuid(organization_id)
        import_application_id = validate_bundle(cards, offers, charges, notes)
        if (
            import_application_id is not None
            and import_application_id != rate_import.id
        ):
            raise ValueError("The parsed rows do not belong to the supplied import")
        with self._pool.connection() as connection:
            self._upsert_import(connection, rate_import, organization_uuid)
            if import_application_id is not None:
                self._replace_import_bundle(
                    connection,
                    import_application_id,
                    cards,
                    offers,
                    charges,
                    notes,
                    organization_uuid,
                )

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
        del canonical_rates
        import_application_id = validate_bundle(cards, offers, charges, notes)
        if (
            import_application_id is not None
            and import_application_id != rate_import.id
        ):
            raise ValueError("The parsed rows do not belong to the supplied import")
        organization_uuid = require_organization_uuid(organization_id)
        approver_uuid = optional_uuid(approved_by_user_id)

        with self._pool.connection() as connection:
            if carrier_key:
                connection.execute(
                    """
                    select pg_advisory_xact_lock(hashtextextended(%s, 0))
                    """,
                    (f"{organization_uuid}:{carrier_key}",),
                )
                rows = connection.execute(
                    """
                    select id, application_id, status, validation_error_count
                    from public.rate_imports
                    where organization_id = %s
                      and (
                        application_id = %s
                        or (carrier_key = %s and status = 'approved')
                      )
                    order by id
                    for update
                    """,
                    (organization_uuid, rate_import.id, carrier_key),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select id, application_id, status, validation_error_count
                    from public.rate_imports
                    where organization_id = %s and application_id = %s
                    for update
                    """,
                    (organization_uuid, rate_import.id),
                ).fetchall()
            target = next(
                (row for row in rows if row["application_id"] == rate_import.id),
                None,
            )
            if target is None:
                raise ValueError(f"Import not found: {rate_import.id}")
            if target["status"] != "pending_review":
                raise ValueError("Only a pending review import can be approved.")
            if target["validation_error_count"]:
                raise ValueError(
                    "Import has blocking validation errors and cannot be approved."
                )

            if cards:
                self._update_cards_for_approval(
                    connection,
                    cards,
                    target["id"],
                    organization_uuid,
                )

            archived_ids = [
                row["id"]
                for row in rows
                if row["application_id"] != rate_import.id
                and row["status"] == "approved"
            ]
            if archived_ids:
                connection.execute(
                    """
                    update public.rate_imports
                    set status = 'archived', archived_at = now()
                    where organization_id = %s and id = any(%s)
                    """,
                    (organization_uuid, archived_ids),
                )
            connection.execute(
                """
                update public.rate_imports
                set status = 'approved',
                    carrier_key = %s,
                    approved_at = now(),
                    approved_by = %s,
                    rejected_at = null,
                    rejected_by = null,
                    rejection_reason = null,
                    archived_at = null,
                    parse_summary = parse_summary || %s
                where organization_id = %s and id = %s
                """,
                (
                    carrier_key,
                    approver_uuid,
                    Jsonb({"approved_by_label": approved_by}),
                    organization_uuid,
                    target["id"],
                ),
            )
            row = self._get_import_row(connection, rate_import.id, organization_uuid)
        if row is None:
            raise ValueError(f"Import not found after approval: {rate_import.id}")
        return rate_import_from_db(row)

    def reject_import(
        self,
        rate_import: RateImport,
        reason: str,
        *,
        organization_id: OrganizationId,
        rejected_by_user_id: str | None = None,
    ) -> RateImport:
        organization_uuid = require_organization_uuid(organization_id)
        rejector_uuid = optional_uuid(rejected_by_user_id)
        with self._pool.connection() as connection:
            row = connection.execute(
                """
                select id, status
                from public.rate_imports
                where organization_id = %s and application_id = %s
                for update
                """,
                (organization_uuid, rate_import.id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Import not found: {rate_import.id}")
            if row["status"] not in {"pending_review", "failed"}:
                raise ValueError("Only a pending or failed import can be rejected.")
            connection.execute(
                """
                update public.rate_imports
                set status = 'rejected',
                    rejected_at = now(),
                    rejected_by = %s,
                    rejection_reason = %s
                where organization_id = %s and id = %s
                """,
                (rejector_uuid, reason, organization_uuid, row["id"]),
            )
            stored = self._get_import_row(
                connection,
                rate_import.id,
                organization_uuid,
            )
        if stored is None:
            raise ValueError(f"Import not found after rejection: {rate_import.id}")
        return rate_import_from_db(stored)

    def remove_import_data(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
        remove_import_record: bool = False,
    ) -> None:
        organization_uuid = require_organization_uuid(organization_id)
        with self._pool.connection() as connection:
            import_database_id = self._optional_application_database_id(
                connection,
                "rate_imports",
                import_id,
                organization_uuid,
            )
            if import_database_id is None:
                return
            if remove_import_record:
                connection.execute(
                    """
                    delete from public.rate_imports
                    where organization_id = %s and id = %s
                    """,
                    (organization_uuid, import_database_id),
                )
            else:
                connection.execute(
                    """
                    delete from public.rate_cards
                    where organization_id = %s and import_id = %s
                    """,
                    (organization_uuid, import_database_id),
                )

    def load_approved_rate_library(
        self,
        *,
        organization_id: OrganizationId,
    ) -> ApprovedRateLibrary:
        organization_uuid = require_organization_uuid(organization_id)
        with self._pool.connection() as connection:
            approved_import_rows = connection.execute(
                """
                select id
                from public.rate_imports
                where organization_id = %s and status = 'approved'
                """,
                (organization_uuid,),
            ).fetchall()
            if not approved_import_rows:
                return ApprovedRateLibrary(
                    cards=(),
                    offers=(),
                    charges=(),
                    notes=(),
                    source_by_import={},
                )
            approved_import_ids = [row["id"] for row in approved_import_rows]
            card_rows = connection.execute(
                """
                select c.id, c.application_id, c.provider, c.carrier,
                       c.commodity, c.currency, c.valid_from, c.valid_to,
                       c.is_all_in, c.document_type, c.metadata, c.created_at,
                       i.application_id as import_application_id
                from public.rate_cards c
                join public.rate_imports i
                  on i.organization_id = c.organization_id and i.id = c.import_id
                where c.organization_id = %s and c.import_id = any(%s)
                order by c.created_at, c.application_id
                """,
                (organization_uuid, approved_import_ids),
            ).fetchall()
            offer_rows = connection.execute(
                """
                select o.id, o.application_id, o.collection, o.origin, o.pol,
                       o.pod, o.destination, o.equipment, o.service_mode,
                       o.base_amount, o.currency, o.routing, o.valid_from,
                       o.valid_to, o.source_reference, o.metadata, o.created_at,
                       c.application_id as card_application_id
                from public.rate_offers o
                join public.rate_cards c
                  on c.organization_id = o.organization_id and c.id = o.rate_card_id
                join public.rate_imports i
                  on i.organization_id = o.organization_id and i.id = o.import_id
                where o.organization_id = %s and o.import_id = any(%s)
                order by o.created_at, o.application_id
                """,
                (organization_uuid, approved_import_ids),
            ).fetchall()
            offer_ids = [row["id"] for row in offer_rows]
            charge_rows = (
                connection.execute(
                    """
                    select ch.id, ch.application_id, ch.charge_name, ch.amount,
                           ch.currency, ch.basis, ch.charge_type, ch.is_included,
                           ch.source_reference, ch.metadata, ch.created_at,
                           ch.rate_offer_id
                    from public.rate_charge_lines ch
                    where ch.organization_id = %s
                      and ch.rate_offer_id = any(%s)
                    order by ch.created_at, ch.application_id
                    """,
                    (organization_uuid, offer_ids),
                ).fetchall()
                if offer_ids
                else []
            )
            note_rows = connection.execute(
                """
                select n.id, n.application_id, n.note_type, n.note_text,
                       n.source_reference, n.metadata, n.created_at,
                       c.application_id as card_application_id,
                       o.application_id as offer_application_id
                from public.rate_notes n
                join public.rate_cards c
                  on c.organization_id = n.organization_id and c.id = n.rate_card_id
                left join public.rate_offers o
                  on o.organization_id = n.organization_id and o.id = n.rate_offer_id
                where n.organization_id = %s and c.import_id = any(%s)
                order by n.created_at, n.application_id
                """,
                (organization_uuid, approved_import_ids),
            ).fetchall()
            source_rows = connection.execute(
                """
                select s.id, s.application_id, s.organization_id,
                       s.original_filename, s.source_type, s.sha256,
                       s.storage_path, s.uploaded_by, s.metadata, s.created_at,
                       i.application_id as import_application_id,
                       i.carrier_key
                from public.source_documents s
                join public.rate_imports i
                  on i.organization_id = s.organization_id
                 and i.source_document_id = s.id
                where s.organization_id = %s and i.id = any(%s)
                """,
                (organization_uuid, approved_import_ids),
            ).fetchall()

        offer_application_ids = {
            row["id"]: row["application_id"] for row in offer_rows
        }
        for row in charge_rows:
            row["offer_application_id"] = offer_application_ids[
                row["rate_offer_id"]
            ]

        source_by_import: dict[str, dict[str, Any]] = {}
        for row in source_rows:
            source = source_document_from_db(row)
            payload = source.model_dump(mode="json")
            payload["operator_carrier_key"] = row.get("carrier_key")
            source_by_import[row["import_application_id"]] = payload
        return ApprovedRateLibrary(
            cards=tuple(rate_card_from_db(row) for row in card_rows),
            offers=tuple(rate_offer_from_db(row) for row in offer_rows),
            charges=tuple(rate_charge_line_from_db(row) for row in charge_rows),
            notes=tuple(rate_note_from_db(row) for row in note_rows),
            source_by_import=source_by_import,
        )

    def _upsert_import(
        self,
        connection: Any,
        rate_import: RateImport,
        organization_id: UUID,
    ) -> None:
        source_database_id = self._application_database_id(
            connection,
            "source_documents",
            rate_import.source_document_id,
            organization_id,
        )
        existing_id = self._optional_application_database_id(
            connection,
            "rate_imports",
            rate_import.id,
            organization_id,
        )
        payload = rate_import_to_db(
            rate_import,
            organization_id=organization_id,
            database_id=existing_id or uuid4(),
            source_document_database_id=source_database_id,
        )
        connection.execute(
            """
            insert into public.rate_imports (
                id, application_id, organization_id, source_document_id,
                template_id, parser_family, match_confidence, status,
                carrier_key, validation_error_count, validation_warning_count,
                validation_report, parse_summary, approved_at, approved_by,
                rejected_at, rejected_by, rejection_reason, archived_at,
                created_at
            ) values (
                %(id)s, %(application_id)s, %(organization_id)s,
                %(source_document_id)s, %(template_id)s, %(parser_family)s,
                %(match_confidence)s, %(status)s, %(carrier_key)s,
                %(validation_error_count)s, %(validation_warning_count)s,
                %(validation_report)s, %(parse_summary)s, %(approved_at)s,
                %(approved_by)s, %(rejected_at)s, %(rejected_by)s,
                %(rejection_reason)s, %(archived_at)s, %(created_at)s
            )
            on conflict (organization_id, application_id) do update set
                source_document_id = excluded.source_document_id,
                template_id = excluded.template_id,
                parser_family = excluded.parser_family,
                match_confidence = excluded.match_confidence,
                status = excluded.status,
                carrier_key = excluded.carrier_key,
                validation_error_count = excluded.validation_error_count,
                validation_warning_count = excluded.validation_warning_count,
                validation_report = excluded.validation_report,
                parse_summary = excluded.parse_summary,
                approved_at = excluded.approved_at,
                approved_by = excluded.approved_by,
                rejected_at = excluded.rejected_at,
                rejected_by = excluded.rejected_by,
                rejection_reason = excluded.rejection_reason,
                archived_at = excluded.archived_at
            """,
            {
                **payload,
                "validation_report": Jsonb(payload["validation_report"]),
                "parse_summary": Jsonb(payload["parse_summary"]),
            },
        )

    def _replace_import_bundle(
        self,
        connection: Any,
        import_application_id: str,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        organization_id: UUID,
    ) -> None:
        import_database_id = self._application_database_id(
            connection,
            "rate_imports",
            import_application_id,
            organization_id,
        )
        connection.execute(
            """
            delete from public.rate_cards
            where organization_id = %s and import_id = %s
            """,
            (organization_id, import_database_id),
        )

        card_ids = {card.id: uuid4() for card in cards}
        offer_ids = {offer.id: uuid4() for offer in offers}
        card_payloads = [
            rate_card_to_db(
                card,
                organization_id=organization_id,
                database_id=card_ids[card.id],
                import_database_id=import_database_id,
            )
            for card in cards
        ]
        offer_payloads = [
            rate_offer_to_db(
                offer,
                organization_id=organization_id,
                database_id=offer_ids[offer.id],
                import_database_id=import_database_id,
                card_database_id=card_ids[offer.rate_card_id],
            )
            for offer in offers
        ]
        offer_by_id = {offer.id: offer for offer in offers}
        charge_payloads = [
            rate_charge_line_to_db(
                charge,
                organization_id=organization_id,
                database_id=uuid4(),
                card_database_id=card_ids[
                    offer_by_id[charge.rate_offer_id].rate_card_id
                ],
                offer_database_id=offer_ids[charge.rate_offer_id],
            )
            for charge in charges
        ]
        note_payloads = [
            rate_note_to_db(
                note,
                organization_id=organization_id,
                database_id=uuid4(),
                card_database_id=card_ids[note.rate_card_id],
                offer_database_id=(
                    offer_ids[note.rate_offer_id] if note.rate_offer_id else None
                ),
            )
            for note in notes
        ]

        self._insert_cards(connection, card_payloads)
        self._insert_offers(connection, offer_payloads)
        self._insert_charges(connection, charge_payloads)
        self._insert_notes(connection, note_payloads)

    @staticmethod
    def _update_cards_for_approval(
        connection: Any,
        cards: list[RateCard],
        import_database_id: UUID,
        organization_id: UUID,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                update public.rate_cards
                set provider = %(provider)s,
                    carrier = %(carrier)s
                where organization_id = %(organization_id)s
                  and import_id = %(import_id)s
                  and application_id = %(application_id)s
                """,
                [
                    {
                        "provider": card.provider_name,
                        "carrier": card.carrier_name,
                        "organization_id": organization_id,
                        "import_id": import_database_id,
                        "application_id": card.id,
                    }
                    for card in cards
                ],
            )

    def _get_import_row(
        self,
        connection: Any,
        import_id: str,
        organization_id: UUID,
    ) -> dict[str, Any] | None:
        return connection.execute(
            f"""
            select {IMPORT_COLUMNS}
            from public.rate_imports i
            join public.source_documents s
              on s.organization_id = i.organization_id
             and s.id = i.source_document_id
            where i.organization_id = %s and i.application_id = %s
            """,
            (organization_id, import_id),
        ).fetchone()

    def _application_database_id(
        self,
        connection: Any,
        table_name: str,
        application_id: str,
        organization_id: UUID,
    ) -> UUID:
        database_id = self._optional_application_database_id(
            connection,
            table_name,
            application_id,
            organization_id,
        )
        if database_id is None:
            raise ValueError(f"{table_name} record not found for {application_id}")
        return database_id

    @staticmethod
    def _optional_application_database_id(
        connection: Any,
        table_name: str,
        application_id: str,
        organization_id: UUID,
    ) -> UUID | None:
        if table_name not in {"source_documents", "rate_imports"}:
            raise ValueError("Unsupported application ID lookup table")
        row = connection.execute(
            f"""
            select id from public.{table_name}
            where organization_id = %s and application_id = %s
            """,
            (organization_id, application_id),
        ).fetchone()
        return row["id"] if row else None

    @staticmethod
    def _insert_cards(connection: Any, payloads: list[dict[str, Any]]) -> None:
        _executemany(
            connection,
            """
            insert into public.rate_cards (
                id, application_id, organization_id, import_id, provider,
                carrier, commodity, currency, valid_from, valid_to, is_all_in,
                document_type, metadata, created_at
            ) values (
                %(id)s, %(application_id)s, %(organization_id)s, %(import_id)s,
                %(provider)s, %(carrier)s, %(commodity)s, %(currency)s,
                %(valid_from)s, %(valid_to)s, %(is_all_in)s, %(document_type)s,
                %(metadata)s, %(created_at)s
            )
            """,
            payloads,
        )

    @staticmethod
    def _insert_offers(connection: Any, payloads: list[dict[str, Any]]) -> None:
        _executemany(
            connection,
            """
            insert into public.rate_offers (
                id, application_id, organization_id, import_id, rate_card_id,
                collection, origin, pol, pod, destination, equipment,
                service_mode, base_amount, currency, routing, valid_from,
                valid_to, source_reference, metadata, created_at
            ) values (
                %(id)s, %(application_id)s, %(organization_id)s, %(import_id)s,
                %(rate_card_id)s, %(collection)s, %(origin)s, %(pol)s, %(pod)s,
                %(destination)s, %(equipment)s, %(service_mode)s,
                %(base_amount)s, %(currency)s, %(routing)s, %(valid_from)s,
                %(valid_to)s, %(source_reference)s, %(metadata)s, %(created_at)s
            )
            """,
            payloads,
        )

    @staticmethod
    def _insert_charges(connection: Any, payloads: list[dict[str, Any]]) -> None:
        _executemany(
            connection,
            """
            insert into public.rate_charge_lines (
                id, application_id, organization_id, rate_card_id,
                rate_offer_id, charge_name, amount, currency, basis,
                charge_type, is_included, source_reference, metadata, created_at
            ) values (
                %(id)s, %(application_id)s, %(organization_id)s,
                %(rate_card_id)s, %(rate_offer_id)s, %(charge_name)s, %(amount)s,
                %(currency)s, %(basis)s, %(charge_type)s, %(is_included)s,
                %(source_reference)s, %(metadata)s, %(created_at)s
            )
            """,
            payloads,
        )

    @staticmethod
    def _insert_notes(connection: Any, payloads: list[dict[str, Any]]) -> None:
        _executemany(
            connection,
            """
            insert into public.rate_notes (
                id, application_id, organization_id, rate_card_id,
                rate_offer_id, note_type, note_text, source_reference,
                metadata, created_at
            ) values (
                %(id)s, %(application_id)s, %(organization_id)s,
                %(rate_card_id)s, %(rate_offer_id)s, %(note_type)s,
                %(note_text)s, %(source_reference)s, %(metadata)s, %(created_at)s
            )
            """,
            payloads,
        )


def secure_connection_string(database_url: str) -> str:
    parameters = conninfo_to_dict(database_url)
    sslmode = parameters.get("sslmode")
    if sslmode in {"disable", "allow", "prefer"}:
        raise ValueError("SUPABASE_DB_URL must require SSL")
    return make_conninfo(
        database_url,
        sslmode=sslmode or "require",
        connect_timeout=parameters.get("connect_timeout") or "5",
        application_name=parameters.get("application_name") or "rate_ingest",
    )


def require_organization_uuid(organization_id: OrganizationId) -> UUID:
    try:
        return UUID(str(organization_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("A valid organization_id UUID is required") from exc


def optional_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("A valid authenticated user UUID is required") from exc


def validate_bundle(
    cards: list[RateCard],
    offers: list[RateOffer],
    charges: list[RateChargeLine],
    notes: list[RateNote],
) -> str | None:
    if not cards:
        if offers or charges or notes:
            raise ValueError("A rate bundle with child rows must include a rate card")
        return None
    import_ids = {card.rate_import_id for card in cards}
    if len(import_ids) != 1:
        raise ValueError("A rate bundle must contain exactly one import")
    card_ids = {card.id for card in cards}
    if len(card_ids) != len(cards):
        raise ValueError("A rate bundle contains duplicate card IDs")
    offer_by_id = {offer.id: offer for offer in offers}
    if len(offer_by_id) != len(offers):
        raise ValueError("A rate bundle contains duplicate offer IDs")
    if any(offer.rate_card_id not in card_ids for offer in offers):
        raise ValueError("A rate offer refers to an unknown rate card")
    if any(charge.rate_offer_id not in offer_by_id for charge in charges):
        raise ValueError("A charge refers to an unknown rate offer")
    if any(note.rate_card_id not in card_ids for note in notes):
        raise ValueError("A note refers to an unknown rate card")
    if any(
        note.rate_offer_id is not None and note.rate_offer_id not in offer_by_id
        for note in notes
    ):
        raise ValueError("A note refers to an unknown rate offer")
    return next(iter(import_ids))


def _executemany(
    connection: Any,
    statement: str,
    payloads: Iterable[dict[str, Any]],
) -> None:
    prepared = [
        {
            **payload,
            "metadata": Jsonb(payload.get("metadata") or {}),
        }
        for payload in payloads
    ]
    if prepared:
        with connection.cursor() as cursor:
            cursor.executemany(statement, prepared)
