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
    freight = extract_freight(full_text)
    efs_amounts = extract_charge_amounts(full_text, r"Emergency Fuel\s+Surcharge \(EFS\)")
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
        import fitz
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
                }
            )
    return pages


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
    heading = re.compile(r"^(.+?) \(Door\).*?via (.+?) \(CY\)", re.IGNORECASE)
    for page in pages:
        lines = page["lines"]
        for index, line in enumerate(lines):
            match = heading.match(line)
            if not match:
                continue
            block_end = next(
                (candidate for candidate in range(index + 1, len(lines)) if heading.match(lines[candidate])),
                min(index + 20, len(lines)),
            )
            block = lines[index + 1 : block_end]
            try:
                currency_index = next(i for i, value in enumerate(block) if re.fullmatch(r"[A-Z]{3}", value))
            except StopIteration:
                continue
            amounts = [parse_money(value) for value in block[currency_index + 1 :] if value != "-"]
            numeric_amounts = [value for value in amounts if value is not None]
            if len(numeric_amounts) < 2:
                continue
            rows.append(
                {
                    "collection": normalize_text(match.group(1)),
                    "via_pol": normalize_text(match.group(2)),
                    "currency": block[currency_index],
                    "amounts": numeric_amounts[:2],
                    "page_number": page["page_number"],
                }
            )
    return rows


def extract_validity(text: str):
    match = re.search(
        r"(\d{2}-[A-Za-z]{3}-\d{4})\s+to\s+(\d{2}-[A-Za-z]{3}-\d{4})",
        text,
    )
    if not match:
        return None, None
    return parse_date_value(match.group(1)), parse_date_value(match.group(2))


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
