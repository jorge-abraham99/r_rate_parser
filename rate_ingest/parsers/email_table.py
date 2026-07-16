from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from dateutil import parser as date_parser

from rate_ingest.email_source import load_email_payload, normalize_cell
from rate_ingest.models import ParserTemplate, RateCard, RateChargeLine, RateImport, RateNote, RateOffer
from rate_ingest.normalize import normalize_text, parse_amount


def parse_email(
    path: Path, template: ParserTemplate, rate_import: RateImport
) -> tuple[RateCard, list[RateOffer], list[RateChargeLine], list[RateNote]]:
    payload = load_email_payload(path)
    frame, table_index = select_table(payload["tables"], template)
    card = RateCard(
        rate_import_id=rate_import.id,
        provider_name=template.provider_name,
        carrier_name=template.defaults.get("carrier_name", template.provider_name),
        document_type=template.document_type,
        commodity=template.defaults.get("commodity"),
        currency_default=template.defaults.get("currency_default"),
        valid_from=None,
        valid_to=None,
        all_in_flag=template.defaults.get("all_in_flag", "unknown"),
        notes_summary=None,
    )
    notes = build_notes(card.id, payload)
    if notes:
        card.notes_summary = notes[0].note_text[:240]
    if frame is None:
        return card, [], [], notes

    rules = template.email_table_rules
    validity_row_index = int(rules.get("validity_row_index", 0))
    destination_row_index = int(rules.get("destination_row_index", 1))
    header_row_index = int(rules.get("header_row_index", 2))
    data_start_row_index = int(rules.get("data_start_row_index", 3))
    origin_column_index = int(rules.get("origin_column_index", 0))
    pol_column_index = int(rules.get("pol_column_index", 1))
    location_name_column_index = int(rules.get("location_name_column_index", 2))
    first_rate_column_index = int(rules.get("first_rate_column_index", 3))
    equipment_by_column = {int(key): value for key, value in rules.get("equipment_by_column", {}).items()}

    valid_from, valid_to = parse_validity(
        cell(frame, validity_row_index, 0),
        payload["received_at"].year if payload["received_at"] else None,
    )
    card.valid_from = valid_from
    card.valid_to = valid_to

    offers: list[RateOffer] = []
    for row_index in range(data_start_row_index, len(frame.index)):
        poo_code = cell(frame, row_index, origin_column_index)
        pol_code = cell(frame, row_index, pol_column_index)
        location_name = cell(frame, row_index, location_name_column_index)
        if not any([poo_code, pol_code, location_name]):
            continue

        for column_index in range(first_rate_column_index, len(frame.columns)):
            raw_value = cell(frame, row_index, column_index)
            amount, trailing_note = parse_amount(raw_value)
            if amount is None:
                continue
            destination_label = cell(frame, destination_row_index, column_index) or cell(frame, header_row_index, column_index)
            if not destination_label:
                continue
            equipment_type = equipment_by_column.get(column_index, template.defaults.get("equipment_type", "UNSPECIFIED"))
            offers.append(
                RateOffer(
                    rate_card_id=card.id,
                    origin=poo_code or None,
                    place_of_receipt=location_name or poo_code or None,
                    pol=pol_code or None,
                    pod=destination_label,
                    final_destination=destination_label,
                    equipment_type=equipment_type,
                    base_amount=amount,
                    base_currency=template.defaults.get("currency_default"),
                    all_in_flag=template.defaults.get("all_in_flag", True),
                    routing_note=trailing_note,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    raw_sheet_name=f"email_table_{table_index}",
                    raw_row_reference=f"email_table_{table_index}!R{row_index + 1}C{column_index + 1}",
                    raw_row_json={
                        "poo_code": poo_code,
                        "pol_code": pol_code,
                        "location_name": location_name,
                        "destination_label": destination_label,
                        "column_header": cell(frame, header_row_index, column_index),
                        "raw_value": raw_value,
                        "email_subject": payload["subject"],
                    },
                )
            )

    return card, offers, [], notes


def select_table(tables, template: ParserTemplate):
    rules = template.email_table_rules
    required_values = [normalize_text(value).upper() for value in rules.get("required_values", [])]
    min_columns = int(rules.get("min_columns", 4))
    for index, frame in enumerate(tables, start=1):
        if len(frame.columns) < min_columns:
            continue
        preview_text = " ".join(
            normalize_cell(value)
            for row_index in range(min(8, len(frame.index)))
            for value in frame.iloc[row_index].tolist()[: min(8, len(frame.columns))]
        ).upper()
        if all(value in preview_text for value in required_values):
            return frame, index
    return None, None


def build_notes(rate_card_id: str, payload: dict) -> list[RateNote]:
    notes: list[RateNote] = []
    if payload["subject"]:
        notes.append(
            RateNote(
                rate_card_id=rate_card_id,
                note_type="email_subject",
                note_text=payload["subject"],
                source_reference="email:subject",
            )
        )
    lines = []
    for raw_line in payload["plain_text"].splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        if line.upper().startswith("VALID FROM"):
            break
        if line not in lines:
            lines.append(line)
        if len(lines) >= 4:
            break
    for index, line in enumerate(lines, start=1):
        notes.append(
            RateNote(
                rate_card_id=rate_card_id,
                note_type="commercial",
                note_text=line,
                source_reference=f"email:plain:{index}",
            )
        )
    return notes


def parse_validity(text: str, fallback_year: int | None):
    normalized = normalize_text(text)
    if not normalized:
        return None, None
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", normalized, flags=re.IGNORECASE)
    match = re.search(r"valid from\s+(.+?)(?:\s+(?:until|to|-)\s+(.+))?$", cleaned, re.IGNORECASE)
    if not match:
        return None, None
    return parse_partial_date(match.group(1), fallback_year), parse_partial_date(match.group(2), fallback_year)


def parse_partial_date(text: str | None, fallback_year: int | None):
    normalized = normalize_text(text)
    if not normalized:
        return None
    normalized = re.sub(r"\bONWARDS\b", "", normalized, flags=re.IGNORECASE).strip(" ,.-")
    if not normalized:
        return None
    default_year = fallback_year or datetime.now().year
    try:
        return date_parser.parse(normalized, dayfirst=True, fuzzy=True, default=datetime(default_year, 1, 1)).date()
    except (ValueError, TypeError, OverflowError):
        return None


def cell(frame, row_index: int, column_index: int) -> str:
    if row_index >= len(frame.index) or column_index >= len(frame.columns):
        return ""
    return normalize_cell(frame.iloc[row_index, column_index])
