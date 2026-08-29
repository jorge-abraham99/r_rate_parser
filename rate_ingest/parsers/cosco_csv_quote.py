from __future__ import annotations

import csv
import re
from pathlib import Path

from rate_ingest.models import (
    ParserTemplate,
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
)
from rate_ingest.normalize import normalize_text, parse_amount
from rate_ingest.parsers.matrix import parse_destination_header


def parse_csv(
    path: Path,
    template: ParserTemplate,
    rate_import: RateImport,
) -> tuple[RateCard, list[RateOffer], list[RateChargeLine], list[RateNote]]:
    rows = load_rows(path)
    card = RateCard(
        rate_import_id=rate_import.id,
        provider_name=template.provider_name,
        carrier_name=template.defaults.get("carrier_name", template.provider_name),
        document_type=template.document_type,
        commodity=template.defaults.get("commodity"),
        currency_default=template.defaults.get("currency_default", "USD"),
        all_in_flag=False,
        notes_summary=(
            "COSCO quay-to-quay rates: basic ocean freight plus EFS. "
            "Origin haulage is supplied separately."
        ),
    )

    offers: list[RateOffer] = []
    charges: list[RateChargeLine] = []
    for row_number, row in enumerate(rows, start=2):
        pol_raw = clean(row.get("POL"))
        pod_raw = clean(row.get("POD"))
        if not pol_raw or not pod_raw:
            continue

        freight, _ = parse_amount(row.get("Freight"))
        efs_amount, efs_currency = parse_efs(row.get("EFS"))
        if freight is None or efs_amount is None:
            continue

        destination = parse_destination_header(pod_raw)
        pol = canonical_port(pol_raw)
        offer = RateOffer(
            rate_card_id=card.id,
            commodity=card.commodity,
            origin=pol,
            place_of_receipt=pol,
            pol=pol,
            pod=destination["to_raw"],
            final_destination=destination["to_raw"],
            equipment_type=template.defaults.get("equipment_type", "40HC"),
            service_mode="CY / CY",
            base_amount=freight,
            base_currency=template.defaults.get("currency_default", "USD"),
            all_in_flag=False,
            routing_note=destination.get("routing_note"),
            raw_sheet_name="csv",
            raw_row_reference=f"csv!R{row_number}",
            raw_row_json={
                "pol_raw": pol_raw,
                "pod_raw": pod_raw,
                "freight_raw": clean(row.get("Freight")),
                "efs_raw": clean(row.get("EFS")),
                "charges_included_raw": clean(row.get("Charges included in freight")),
                "source_file_name": path.name,
            },
        )
        offers.append(offer)
        charges.append(
            RateChargeLine(
                rate_offer_id=offer.id,
                charge_name="Emergency Fuel Surcharge",
                charge_type="surcharge",
                basis="per_container",
                amount=efs_amount,
                currency=efs_currency or card.currency_default,
                included_flag=False,
                source_label="EFS",
                raw_value=clean(row.get("EFS")),
            )
        )

    notes = [
        RateNote(
            rate_card_id=card.id,
            note_type="commercial",
            note_text=(
                "EFS was converted from the source text, including values such as "
                "'Subj EFS (USD 100) per 40ft'."
            ),
            source_reference=path.name,
        )
    ]
    return card, offers, charges, notes


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {normalize_text(key): normalize_text(value) for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def parse_efs(raw: object) -> tuple[float | None, str | None]:
    text = normalize_text(raw)
    if not text:
        return None, None
    match = re.search(
        r"\b(?:US\s*\$|USD)\s*([0-9]+(?:\.[0-9]+)?)\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return float(match.group(1)), "USD"


def canonical_port(raw: str) -> str:
    text = normalize_text(raw).upper()
    if "FELIXSTOWE" in text or text == "GBFXT":
        return "Felixstowe"
    if "SOUTHAMPTON" in text or text == "GBSOU":
        return "Southampton"
    return normalize_text(raw)


def clean(value: object) -> str:
    return normalize_text(value)
