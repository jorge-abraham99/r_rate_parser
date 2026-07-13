from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as date_parser


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_equipment(value: str, template_defaults: dict | None = None) -> tuple[str, str | None]:
    raw = normalize_text(value).upper()
    if not raw:
        return "", "missing_equipment_type"
    mapping = {
        "20": "20GP",
        "20FT": "20GP",
        "20DV": "20GP",
        "20GP": "20GP",
        "40": template_defaults.get("forty_default", "40HC") if template_defaults else "40HC",
        "40GP": "40GP",
        "40HC": "40HC",
        "40HQ": "40HC",
        "FEU": template_defaults.get("feu_default", "40HC") if template_defaults else "40HC",
    }
    return mapping.get(raw, raw), None if raw in mapping else "ambiguous_equipment_type"


def parse_amount(raw: object) -> tuple[float | None, str | None]:
    text = normalize_text(raw)
    if not text or text.upper() in {"POA", "N/A", "-"}:
        return None, None
    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None, None
    amount = float(match.group(0))
    tail = normalize_text(text[match.end() :]) or None
    return amount, tail


def parse_date_range(raw: object) -> tuple[date | None, date | None]:
    text = normalize_text(raw)
    if not text:
        return None, None
    if " - " in text:
        start_text, end_text = text.split(" - ", 1)
        return parse_date_value(start_text), parse_date_value(end_text)
    return parse_date_value(text), None


def parse_date_value(raw: object) -> date | None:
    text = normalize_text(raw)
    if not text:
        return None
    try:
        return date_parser.parse(text, dayfirst=True, fuzzy=True).date()
    except (ValueError, TypeError, OverflowError):
        return None

