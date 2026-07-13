from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class SourceDocument(BaseModel):
    id: str = Field(default_factory=lambda: new_id("src"))
    source_type: str
    file_name: str
    source_path: str
    provider_name: str | None = None
    received_at: datetime | None = None
    uploaded_by: str | None = None
    checksum: str
    status: str = "registered"
    created_at: datetime = Field(default_factory=utc_now)


class RateImport(BaseModel):
    id: str
    source_document_id: str
    parser_family: str
    template_id: str | None = None
    classification_confidence: float | None = None
    status: str
    validation_summary_json: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class RateCard(BaseModel):
    id: str = Field(default_factory=lambda: new_id("card"))
    rate_import_id: str
    provider_name: str | None = None
    carrier_name: str | None = None
    document_type: str
    commodity: str | None = None
    currency_default: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    all_in_flag: bool | Literal["unknown"] | None = "unknown"
    notes_summary: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class RateOffer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("offer"))
    rate_card_id: str
    offer_reference: str | None = None
    origin: str | None = None
    place_of_receipt: str | None = None
    pol: str | None = None
    pod: str | None = None
    final_destination: str | None = None
    zone: str | None = None
    equipment_type: str
    service_mode: str | None = None
    transit_time_days: int | None = None
    base_amount: float | None = None
    base_currency: str | None = None
    all_in_flag: bool | Literal["unknown"] | None = "unknown"
    routing_note: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    raw_sheet_name: str | None = None
    raw_row_reference: str | None = None
    raw_row_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RateChargeLine(BaseModel):
    id: str = Field(default_factory=lambda: new_id("charge"))
    rate_offer_id: str
    charge_name: str
    charge_type: str | None = None
    basis: str | None = None
    amount: float | None = None
    currency: str | None = None
    included_flag: bool | Literal["unknown"] | None = "unknown"
    source_label: str | None = None
    raw_value: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class RateNote(BaseModel):
    id: str = Field(default_factory=lambda: new_id("note"))
    rate_card_id: str
    rate_offer_id: str | None = None
    note_type: str
    note_text: str
    source_reference: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class CanonicalRate(BaseModel):
    rate_type: str
    from_raw: str
    to_raw: str
    amount: float
    currency: str | None = None
    unit: str = "per_container"
    valid_from: date | None = None
    valid_to: date | None = None


class ValidationItem(BaseModel):
    severity: Literal["ERROR", "WARNING", "INFO"]
    rule_id: str
    entity_type: str
    entity_id: str | None = None
    message: str
    source_reference: str | None = None


class ValidationReport(BaseModel):
    import_id: str
    summary: dict[str, int]
    items: list[ValidationItem] = Field(default_factory=list)


class ParserTemplate(BaseModel):
    template_id: str
    template_name: str
    provider_name: str | None = None
    parser_family: str
    document_type: str
    file_type: str
    active: bool = True
    match_rules: dict[str, Any] = Field(default_factory=dict)
    sheet_rules: dict[str, Any] = Field(default_factory=dict)
    header_detection: dict[str, Any] = Field(default_factory=dict)
    field_map: dict[str, str] = Field(default_factory=dict)
    breakdown_columns: list[dict[str, Any]] = Field(default_factory=list)
    normalizers: dict[str, Any] = Field(default_factory=dict)
    row_filters: dict[str, Any] = Field(default_factory=dict)
    note_extraction: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)


class InspectResult(BaseModel):
    source_document: SourceDocument
    workbook_type: str
    provider_guess: str | None = None
    parser_family_guess: str | None = None
    sheet_summaries: list[dict[str, Any]] = Field(default_factory=list)
    possible_templates: list[dict[str, Any]] = Field(default_factory=list)
