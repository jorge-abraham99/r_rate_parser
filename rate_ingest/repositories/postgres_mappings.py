from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python

from rate_ingest.models import (
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
    SourceDocument,
)


def source_document_to_db(
    source: SourceDocument,
    *,
    organization_id: UUID,
    database_id: UUID,
) -> dict[str, Any]:
    uploaded_by = _uuid_or_none(source.uploaded_by)
    metadata = {
        "provider_name": source.provider_name,
        "received_at": source.received_at.isoformat() if source.received_at else None,
        "status": source.status,
    }
    if source.uploaded_by and uploaded_by is None:
        metadata["uploaded_by_label"] = source.uploaded_by
    return {
        "id": database_id,
        "application_id": source.id,
        "organization_id": organization_id,
        "original_filename": source.file_name,
        "source_type": source.source_type,
        "sha256": source.checksum,
        "storage_path": source.source_path,
        "uploaded_by": uploaded_by,
        "metadata": _json_mapping(metadata),
        "created_at": source.created_at,
    }


def source_document_from_db(row: dict[str, Any]) -> SourceDocument:
    metadata = _metadata(row)
    uploaded_by = row.get("uploaded_by") or metadata.get("uploaded_by_label")
    return SourceDocument(
        id=row["application_id"],
        source_type=row["source_type"],
        file_name=row["original_filename"],
        source_path=row.get("storage_path") or "",
        provider_name=metadata.get("provider_name"),
        received_at=metadata.get("received_at"),
        uploaded_by=str(uploaded_by) if uploaded_by else None,
        checksum=row["sha256"],
        status=metadata.get("status") or "registered",
        created_at=row["created_at"],
    )


def rate_import_to_db(
    rate_import: RateImport,
    *,
    organization_id: UUID,
    database_id: UUID,
    source_document_database_id: UUID,
) -> dict[str, Any]:
    approved_by = _uuid_or_none(rate_import.approved_by)
    rejected_by = _uuid_or_none(rate_import.rejected_by)
    validation = dict(rate_import.validation_summary_json)
    metadata: dict[str, Any] = {}
    if rate_import.approved_by and approved_by is None:
        metadata["approved_by_label"] = rate_import.approved_by
    if rate_import.rejected_by and rejected_by is None:
        metadata["rejected_by_label"] = rate_import.rejected_by
    return {
        "id": database_id,
        "application_id": rate_import.id,
        "organization_id": organization_id,
        "source_document_id": source_document_database_id,
        "template_id": rate_import.template_id,
        "parser_family": rate_import.parser_family,
        "match_confidence": _decimal_or_none(rate_import.classification_confidence),
        "status": rate_import.status,
        "carrier_key": rate_import.carrier_key,
        "validation_error_count": int(validation.get("errors", 0) or 0),
        "validation_warning_count": int(validation.get("warnings", 0) or 0),
        "validation_report": _json_mapping(validation),
        "parse_summary": _json_mapping(metadata),
        "approved_at": rate_import.approved_at,
        "approved_by": approved_by,
        "rejected_at": rate_import.rejected_at,
        "rejected_by": rejected_by,
        "rejection_reason": rate_import.rejection_reason,
        "archived_at": rate_import.archived_at,
        "created_at": rate_import.created_at,
    }


def rate_import_from_db(row: dict[str, Any]) -> RateImport:
    parse_summary = row.get("parse_summary") or {}
    approved_by = parse_summary.get("approved_by_label") or row.get("approved_by")
    rejected_by = parse_summary.get("rejected_by_label") or row.get("rejected_by")
    return RateImport(
        id=row["application_id"],
        source_document_id=row["source_application_id"],
        parser_family=row.get("parser_family") or "unknown",
        template_id=row.get("template_id"),
        classification_confidence=_float_or_none(row.get("match_confidence")),
        status=row["status"],
        carrier_key=row.get("carrier_key"),
        validation_summary_json=row.get("validation_report") or {},
        approved_by=str(approved_by) if approved_by else None,
        approved_at=row.get("approved_at"),
        rejected_by=str(rejected_by) if rejected_by else None,
        rejected_at=row.get("rejected_at"),
        rejection_reason=row.get("rejection_reason"),
        archived_at=row.get("archived_at"),
        created_at=row["created_at"],
    )


def rate_card_to_db(
    card: RateCard,
    *,
    organization_id: UUID,
    database_id: UUID,
    import_database_id: UUID,
) -> dict[str, Any]:
    return {
        "id": database_id,
        "application_id": card.id,
        "organization_id": organization_id,
        "import_id": import_database_id,
        "provider": card.provider_name,
        "carrier": card.carrier_name,
        "commodity": card.commodity,
        "currency": card.currency_default,
        "valid_from": card.valid_from,
        "valid_to": card.valid_to,
        "is_all_in": card.all_in_flag if isinstance(card.all_in_flag, bool) else False,
        "document_type": card.document_type,
        "metadata": _json_mapping(
            {
                "all_in_flag": card.all_in_flag,
                "notes_summary": card.notes_summary,
            }
        ),
        "created_at": card.created_at,
    }


def rate_card_from_db(row: dict[str, Any]) -> RateCard:
    metadata = _metadata(row)
    return RateCard(
        id=row["application_id"],
        rate_import_id=row["import_application_id"],
        provider_name=row.get("provider"),
        carrier_name=row.get("carrier"),
        document_type=row.get("document_type") or "unknown",
        commodity=row.get("commodity"),
        currency_default=row.get("currency"),
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        all_in_flag=metadata.get("all_in_flag", row.get("is_all_in")),
        notes_summary=metadata.get("notes_summary"),
        created_at=row["created_at"],
    )


def rate_offer_to_db(
    offer: RateOffer,
    *,
    organization_id: UUID,
    database_id: UUID,
    import_database_id: UUID,
    card_database_id: UUID,
) -> dict[str, Any]:
    return {
        "id": database_id,
        "application_id": offer.id,
        "organization_id": organization_id,
        "import_id": import_database_id,
        "rate_card_id": card_database_id,
        "collection": offer.place_of_receipt,
        "origin": offer.origin,
        "pol": offer.pol,
        "pod": offer.pod,
        "destination": offer.final_destination,
        "equipment": offer.equipment_type,
        "service_mode": offer.service_mode,
        "base_amount": _decimal_or_none(offer.base_amount),
        "currency": offer.base_currency,
        "routing": offer.routing_note,
        "valid_from": offer.valid_from,
        "valid_to": offer.valid_to,
        "source_reference": offer.raw_row_reference,
        "metadata": _json_mapping(
            {
                "offer_reference": offer.offer_reference,
                "commodity": offer.commodity,
                "zone": offer.zone,
                "transit_time_days": offer.transit_time_days,
                "all_in_flag": offer.all_in_flag,
                "raw_sheet_name": offer.raw_sheet_name,
                "raw_row_json": offer.raw_row_json,
            }
        ),
        "created_at": offer.created_at,
    }


def rate_offer_from_db(row: dict[str, Any]) -> RateOffer:
    metadata = _metadata(row)
    return RateOffer(
        id=row["application_id"],
        rate_card_id=row["card_application_id"],
        offer_reference=metadata.get("offer_reference"),
        commodity=metadata.get("commodity"),
        origin=row.get("origin"),
        place_of_receipt=row.get("collection"),
        pol=row.get("pol"),
        pod=row.get("pod"),
        final_destination=row.get("destination"),
        zone=metadata.get("zone"),
        equipment_type=row["equipment"],
        service_mode=row.get("service_mode"),
        transit_time_days=metadata.get("transit_time_days"),
        base_amount=_float_or_none(row.get("base_amount")),
        base_currency=row.get("currency"),
        all_in_flag=metadata.get("all_in_flag", "unknown"),
        routing_note=row.get("routing"),
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        raw_sheet_name=metadata.get("raw_sheet_name"),
        raw_row_reference=row.get("source_reference"),
        raw_row_json=metadata.get("raw_row_json") or {},
        created_at=row["created_at"],
    )


def rate_charge_line_to_db(
    charge: RateChargeLine,
    *,
    organization_id: UUID,
    database_id: UUID,
    card_database_id: UUID,
    offer_database_id: UUID,
) -> dict[str, Any]:
    return {
        "id": database_id,
        "application_id": charge.id,
        "organization_id": organization_id,
        "rate_card_id": card_database_id,
        "rate_offer_id": offer_database_id,
        "charge_name": charge.charge_name,
        "amount": _decimal_or_none(charge.amount),
        "currency": charge.currency,
        "basis": charge.basis,
        "charge_type": charge.charge_type,
        "is_included": (
            charge.included_flag if isinstance(charge.included_flag, bool) else False
        ),
        "source_reference": charge.source_label,
        "metadata": _json_mapping(
            {
                "included_flag": charge.included_flag,
                "raw_value": charge.raw_value,
            }
        ),
        "created_at": charge.created_at,
    }


def rate_charge_line_from_db(row: dict[str, Any]) -> RateChargeLine:
    metadata = _metadata(row)
    return RateChargeLine(
        id=row["application_id"],
        rate_offer_id=row["offer_application_id"],
        charge_name=row["charge_name"],
        charge_type=row.get("charge_type"),
        basis=row.get("basis"),
        amount=_float_or_none(row.get("amount")),
        currency=row.get("currency"),
        included_flag=metadata.get("included_flag", row.get("is_included")),
        source_label=row.get("source_reference"),
        raw_value=metadata.get("raw_value"),
        created_at=row["created_at"],
    )


def rate_note_to_db(
    note: RateNote,
    *,
    organization_id: UUID,
    database_id: UUID,
    card_database_id: UUID,
    offer_database_id: UUID | None,
) -> dict[str, Any]:
    return {
        "id": database_id,
        "application_id": note.id,
        "organization_id": organization_id,
        "rate_card_id": card_database_id,
        "rate_offer_id": offer_database_id,
        "note_type": note.note_type,
        "note_text": note.note_text,
        "source_reference": note.source_reference,
        "metadata": {},
        "created_at": note.created_at,
    }


def rate_note_from_db(row: dict[str, Any]) -> RateNote:
    return RateNote(
        id=row["application_id"],
        rate_card_id=row["card_application_id"],
        rate_offer_id=row.get("offer_application_id"),
        note_type=row.get("note_type") or "unknown",
        note_text=row["note_text"],
        source_reference=row.get("source_reference"),
        created_at=row["created_at"],
    )


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _json_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return to_jsonable_python(value)


def _decimal_or_none(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None


def _uuid_or_none(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
