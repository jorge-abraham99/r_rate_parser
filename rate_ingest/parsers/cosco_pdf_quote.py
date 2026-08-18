from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rate_ingest.models import ParserTemplate, RateCard, RateChargeLine, RateImport, RateNote, RateOffer
from rate_ingest.normalize import normalize_text, parse_amount, parse_date_value


EQUIPMENT_COLUMNS = (("40GP", 0), ("40HC", 1))


def parse_pdf(
    path: Path,
    template: ParserTemplate,
    rate_import: RateImport,
) -> tuple[RateCard, list[RateOffer], list[RateChargeLine], list[RateNote]]:
    pages = extract_pages(path)
    full_text = "\n".join(page["text"] for page in pages)
    rules = template.cosco_pdf_rules
    equipment_columns = extract_equipment_columns(pages)
    freight = extract_freight_from_words(pages, equipment_columns) or extract_freight(full_text)
    efs_amounts = extract_efs_from_words(pages, equipment_columns) or extract_charge_amounts(
        full_text,
        r"Emergency Fuel\s+Surcharge \(EFS\)",
    )
    haulage_rows = extract_haulage_rows(pages)
    valid_from, valid_to = extract_validity(full_text)
    document_reference = extract_document_reference(full_text)

    if not freight:
        raise ValueError("COSCO PDF parser could not find the Freight Rate block.")
    if not efs_amounts:
        raise ValueError("COSCO PDF parser could not find the Emergency Fuel Surcharge block.")
    if not haulage_rows:
        raise ValueError("COSCO PDF parser could not find any Inland Haulage at Load rows.")

    currency = freight["currency"]
    card = RateCard(
        rate_import_id=rate_import.id,
        provider_name=template.provider_name,
        carrier_name=template.defaults.get("carrier_name", template.provider_name),
        document_type=template.document_type,
        commodity=template.defaults.get("commodity"),
        currency_default=currency,
        valid_from=valid_from,
        valid_to=valid_to,
        all_in_flag=False,
        notes_summary="COSCO India/Far East door-to-quay quote: Freight + EFS + origin haulage only.",
    )

    offers: list[RateOffer] = []
    charges: list[RateChargeLine] = []
    for haulage in haulage_rows:
        for equipment_type, amount_index in EQUIPMENT_COLUMNS:
            freight_amount = value_at(freight["amounts"], amount_index)
            efs_amount = value_at(efs_amounts["amounts"], amount_index)
            haulage_amount = value_at(haulage["amounts"], amount_index)
            if freight_amount is None or efs_amount is None or haulage_amount is None:
                continue
            offer = RateOffer(
                rate_card_id=card.id,
                offer_reference=document_reference,
                commodity=card.commodity,
                origin=haulage["collection"],
                place_of_receipt=haulage["collection"],
                pol=freight["pol"],
                pod=freight["pod"],
                final_destination=freight["pod"],
                equipment_type=equipment_type,
                service_mode="SD / CY",
                base_amount=freight_amount,
                base_currency=currency,
                all_in_flag=False,
                routing_note=f"Truck via {haulage['via_pol']}",
                valid_from=valid_from,
                valid_to=valid_to,
                raw_sheet_name=f"PDF page {haulage['page_number']}",
                raw_row_reference=f"page {haulage['page_number']}: {haulage['collection']} IHL",
                raw_row_json={
                    "document_reference": document_reference,
                    "collection": haulage["collection"],
                    "via_pol": haulage["via_pol"],
                    "pod": freight["pod"],
                    "equipment_type": equipment_type,
                    "freight": freight_amount,
                    "emergency_fuel_surcharge": efs_amount,
                    "inland_haulage_at_load": haulage_amount,
                },
            )
            offers.append(offer)
            charges.extend(
                [
                    RateChargeLine(
                        rate_offer_id=offer.id,
                        charge_name="Emergency Fuel Surcharge",
                        charge_type="freight",
                        basis="per_container",
                        amount=efs_amount,
                        currency=efs_amounts["currency"],
                        included_flag=False,
                        source_label="Emergency Fuel Surcharge (EFS)",
                        raw_value=f"{efs_amounts['currency']} {efs_amount:g}",
                    ),
                    RateChargeLine(
                        rate_offer_id=offer.id,
                        charge_name="Inland Haulage at Load",
                        charge_type="origin",
                        basis="per_container",
                        amount=haulage_amount,
                        currency=haulage["currency"],
                        included_flag=False,
                        source_label="Inland Haulage at Load (IHL)",
                        raw_value=f"{haulage['currency']} {haulage_amount:g}",
                    ),
                ]
            )

    notes = build_notes(card.id, full_text, document_reference)
    return card, offers, charges, notes


def extract_pages(path: Path) -> list[dict[str, Any]]:
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise ValueError("COSCO PDF parsing requires the pymupdf package.") from exc

    pages: list[dict[str, Any]] = []
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True)
            pages.append(
                {
                    "page_number": page_number,
                    "text": text,
                    "lines": [normalize_text(line) for line in text.splitlines() if normalize_text(line)],
                    "words": page.get_text("words", sort=True),
                }
            )
    return pages


def extract_equipment_columns(pages: list[dict[str, Any]]) -> tuple[float, float]:
    for page in pages:
        forty_headers = [word for word in page["words"] if word_text(word) == "40'"]
        for header in forty_headers:
            same_row = [
                word for word in forty_headers
                if abs(word_y(word) - word_y(header)) < 2
            ]
            if len(same_row) >= 2:
                centers = sorted(word_x(word) for word in same_row)
                return centers[0], centers[1]
    raise ValueError("COSCO PDF parser could not locate the 40GP and 40HC columns.")


def extract_freight_from_words(
    pages: list[dict[str, Any]],
    equipment_columns: tuple[float, float],
) -> dict[str, Any] | None:
    for page in pages:
        words = page["words"]
        for index, word in enumerate(words):
            if word_text(word).lower() != "freight":
                continue
            rate_word = next(
                (
                    candidate for candidate in words[index + 1 : index + 5]
                    if word_text(candidate).lower() == "rate"
                    and abs(word_y(candidate) - word_y(word)) < 2
                ),
                None,
            )
            if not rate_word:
                continue
            currency_word = find_currency_word(words, word_y(word), tolerance=18)
            if not currency_word:
                continue
            lane = find_lane(words, word_y(word), word[2])
            amounts = amounts_at_columns(words, word_y(currency_word), equipment_columns)
            if lane and all(amount is not None for amount in amounts):
                return {
                    "pol": lane[0],
                    "pod": lane[1],
                    "currency": word_text(currency_word).upper(),
                    "amounts": amounts,
                }
    return None


def extract_efs_from_words(
    pages: list[dict[str, Any]],
    equipment_columns: tuple[float, float],
) -> dict[str, Any] | None:
    for page in pages:
        words = page["words"]
        for word in words:
            if word_text(word).upper() != "(EFS)":
                continue
            currency_word = find_currency_word(words, word_y(word), tolerance=18)
            if not currency_word:
                continue
            amounts = amounts_at_columns(words, word_y(currency_word), equipment_columns)
            if all(amount is not None for amount in amounts):
                return {
                    "currency": word_text(currency_word).upper(),
                    "amounts": amounts,
                }
    return None


def extract_freight(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"Freight Rate\s+([A-Za-z .'-]+?)\s+to\s+([A-Za-z ,.'-]+?)\s+([A-Z]{3})\s+-\s+([\d,.-]+)\s+([\d,.-]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "pol": normalize_text(match.group(1)),
        "pod": normalize_text(match.group(2)),
        "currency": match.group(3).upper(),
        "amounts": [parse_money(match.group(4)), parse_money(match.group(5))],
    }


def extract_charge_amounts(text: str, label_pattern: str) -> dict[str, Any] | None:
    match = re.search(
        rf"{label_pattern}\s+([A-Z]{{3}})\s+-\s+([\d,.-]+)\s+([\d,.-]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "currency": match.group(1).upper(),
        "amounts": [parse_money(match.group(2)), parse_money(match.group(3))],
    }


def extract_haulage_rows(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        words = page["words"]
        door_words = [word for word in words if word_text(word).lower() == "(door)"]
        for door_index, door_word in enumerate(door_words):
            line_words = sorted(
                [word for word in words if abs(word_y(word) - word_y(door_word)) < 2],
                key=lambda word: word[0],
            )
            try:
                door_position = line_words.index(door_word)
                via_position = next(
                    index for index, word in enumerate(line_words)
                    if word_text(word).lower() == "via"
                )
                cy_position = next(
                    index for index, word in enumerate(line_words[via_position + 1 :], start=via_position + 1)
                    if word_text(word).lower() == "(cy)"
                )
            except (ValueError, StopIteration):
                continue
            collection = normalize_text(" ".join(word_text(word) for word in line_words[:door_position]))
            via_pol = normalize_text(" ".join(word_text(word) for word in line_words[via_position + 1 : cy_position]))
            next_door_y = (
                word_y(door_words[door_index + 1])
                if door_index + 1 < len(door_words)
                else word_y(door_word) + 45
            )
            block_words = [
                word for word in words
                if word_y(door_word) < word_y(word) < next_door_y
            ]
            if not any(word_text(word).upper() == "(IHL)" for word in block_words):
                continue
            currency_word = find_currency_word(block_words, word_y(door_word) + 18, tolerance=18)
            if not currency_word:
                continue
            amounts = amounts_at_columns(words, word_y(currency_word), extract_equipment_columns([page]))
            if any(amount is None for amount in amounts):
                continue
            rows.append(
                {
                    "collection": collection,
                    "via_pol": via_pol,
                    "currency": word_text(currency_word).upper(),
                    "amounts": amounts,
                    "page_number": page["page_number"],
                }
            )
    return rows


def find_currency_word(words: list[tuple], anchor_y: float, tolerance: float) -> tuple | None:
    currencies = [
        word for word in words
        if re.fullmatch(r"[A-Z]{3}", word_text(word))
        and abs(word_y(word) - anchor_y) <= tolerance
    ]
    return min(currencies, key=lambda word: abs(word_y(word) - anchor_y)) if currencies else None


def find_lane(words: list[tuple], anchor_y: float, right_edge: float) -> tuple[str, str] | None:
    candidates = [
        word for word in words
        if word_text(word).lower() == "to"
        and anchor_y <= word_y(word) <= anchor_y + 25
        and word[0] < right_edge + 70
    ]
    if not candidates:
        return None
    to_word = min(candidates, key=lambda word: word_y(word))
    lane_words = sorted(
        [word for word in words if abs(word_y(word) - word_y(to_word)) < 2 and word[0] < 145],
        key=lambda word: word[0],
    )
    try:
        to_position = lane_words.index(to_word)
    except ValueError:
        return None
    pol = normalize_text(" ".join(word_text(word) for word in lane_words[:to_position]))
    pod = normalize_text(" ".join(word_text(word) for word in lane_words[to_position + 1 :]))
    return (pol, pod) if pol and pod else None


def amounts_at_columns(
    words: list[tuple],
    row_y: float,
    equipment_columns: tuple[float, float],
) -> list[float | None]:
    amounts: list[float | None] = []
    for column_x in equipment_columns:
        candidates = [
            word for word in words
            if abs(word_y(word) - row_y) < 4
            and abs(word_x(word) - column_x) < 16
            and parse_money(word_text(word)) is not None
        ]
        candidate = min(candidates, key=lambda word: abs(word_x(word) - column_x)) if candidates else None
        amounts.append(parse_money(word_text(candidate)) if candidate else None)
    return amounts


def word_text(word: tuple) -> str:
    return normalize_text(word[4])


def word_x(word: tuple) -> float:
    return (float(word[0]) + float(word[2])) / 2


def word_y(word: tuple) -> float:
    return (float(word[1]) + float(word[3])) / 2


def extract_validity(text: str):
    match = re.search(
        r"(\d{2}-[A-Za-z]{3}-\d{4})\s+to\s+(\d{2}-[A-Za-z]{3}-\d{4})",
        text,
    )
    if match:
        return parse_date_value(match.group(1)), parse_date_value(match.group(2))

    period_start = text.lower().find("rate effective period")
    if period_start < 0:
        return None, None
    period_text = text[period_start : period_start + 1500]
    dates = re.findall(r"\d{2}-[A-Za-z]{3}-\d{4}", period_text)
    if len(dates) < 2:
        return None, None
    return parse_date_value(dates[0]), parse_date_value(dates[1])


def extract_document_reference(text: str) -> str | None:
    match = re.search(r"Document No\.\s+(\d+)", text, re.IGNORECASE)
    return match.group(1) if match else None


def build_notes(rate_card_id: str, text: str, document_reference: str | None) -> list[RateNote]:
    notes: list[RateNote] = []
    if document_reference:
        notes.append(
            RateNote(
                rate_card_id=rate_card_id,
                note_type="reference",
                note_text=f"COSCO document {document_reference}",
                source_reference="page 1",
            )
        )
    included_match = re.search(r"Freight Rates are inclusive of (.+?)\.\s+Rate Conditions", text, re.DOTALL)
    if included_match:
        notes.append(
            RateNote(
                rate_card_id=rate_card_id,
                note_type="included_charges",
                note_text=normalize_text(included_match.group(1)),
                source_reference="page 1",
            )
        )
    return notes


def parse_money(value: Any) -> float | None:
    amount, _ = parse_amount(value)
    return amount


def value_at(values: list[float | None], index: int) -> float | None:
    return values[index] if index < len(values) else None
