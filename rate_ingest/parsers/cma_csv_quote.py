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
from rate_ingest.parsers.cosco_csv_quote import canonical_port


DESTINATION_LABELS = {
    "MYPKG": "Port Klang, MY",
    "VNVUT": "Vung Tau, VN",
    "VNSGN": "Ho Chi Minh, VN",
    "VNHPH": "Hai Phong, VN",
    "IDJKT": "Jakarta, ID",
    "THLCH": "Laem Chabang, TH",
    "THLKR": "Lat Krabang, TH",
    "THBKK": "Bangkok, TH",
    "VNBDG": "Binh Duong Terminal, VN",
}


def parse_csv(
    path: Path,
    template: ParserTemplate,
    rate_import: RateImport,
) -> tuple[RateCard, list[RateOffer], list[RateChargeLine], list[RateNote]]:
    headers, rows = load_rows(path)
    rules = template.csv_rules
    destination_start = int(rules.get("destination_start_column", 3))
    destination_headers = headers[destination_start:]
    currency = str(template.defaults.get("currency_default", "USD")).upper()
    equipment_type = template.defaults.get("equipment_type", "UNSPECIFIED")

    card = RateCard(
        rate_import_id=rate_import.id,
        provider_name=template.provider_name,
        carrier_name=template.defaults.get("carrier_name", template.provider_name),
        document_type=template.document_type,
        commodity=template.defaults.get("commodity"),
        currency_default=currency,
        all_in_flag=False,
        notes_summary=(
            "CMA door-to-quay rates: pickup location to UK POL to destination. "
            "Freight is USD; documentation and export declaration fees are additional GBP charges."
        ),
    )

    offers: list[RateOffer] = []
    charges: list[RateChargeLine] = []
    for row_number, row in enumerate(rows, start=2):
        poo_code = clean(row.get(rules.get("poo_column", "POO")))
        pickup = clean(row.get(rules.get("pickup_column", "PICK-UP")))
        pol_raw = clean(row.get(rules.get("pol_column", "POL/POD")))
        if not pickup or not pol_raw:
            continue

        pol = canonical_port(pol_raw)
        for destination_header in destination_headers:
            raw_value = clean(row.get(destination_header))
            amount, trailing_note = parse_amount(raw_value)
            if amount is None:
                continue
            for destination_code in split_destination_codes(destination_header):
                destination_name = DESTINATION_LABELS.get(destination_code, destination_code)
                offer = RateOffer(
                    rate_card_id=card.id,
                    commodity=card.commodity,
                    origin=pickup,
                    place_of_receipt=pickup,
                    pol=pol,
                    pod=destination_code,
                    final_destination=destination_code,
                    destination_location_name=destination_name,
                    equipment_type=equipment_type,
                    service_mode="SD / CY",
                    base_amount=amount,
                    base_currency=currency,
                    all_in_flag=False,
                    routing_note=trailing_note,
                    raw_sheet_name="csv",
                    raw_row_reference=f"csv!R{row_number}C{headers.index(destination_header) + 1}",
                    raw_row_json={
                        "poo_raw": poo_code,
                        "pickup_raw": pickup,
                        "pol_raw": pol_raw,
                        "destination_source_code": destination_code,
                        "destination_header": destination_header,
                        "destination_name": destination_name,
                        "freight_raw": raw_value,
                        "source_file_name": path.name,
                    },
                )
                offers.append(offer)
                for charge in template.csv_rules.get("additional_charges", []):
                    charge_name = str(charge.get("name", "Additional charge"))
                    charge_amount = float(charge["amount"])
                    charge_currency = str(charge.get("currency", "GBP")).upper()
                    basis = str(charge.get("basis", "per_bill_of_lading"))
                    charges.append(
                        RateChargeLine(
                            rate_offer_id=offer.id,
                            charge_name=charge_name,
                            charge_type=str(charge.get("charge_type", "origin")),
                            basis=basis,
                            amount=charge_amount,
                            currency=charge_currency,
                            included_flag=False,
                            source_label=f"{charge_name} {charge_currency} {charge_amount:g}",
                            raw_value=f"{charge_currency} {charge_amount:g} {basis}",
                        )
                    )

    notes = [
        RateNote(
            rate_card_id=card.id,
            note_type="commercial",
            note_text=(
                "Destination headers were expanded from UN/LOCODE groups into individual offers. "
                "The source contains no validity dates or equipment column; the template default is 40HC."
            ),
            source_reference=path.name,
        )
    ]
    return card, offers, charges, notes


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [normalize_text(header) for header in reader.fieldnames or []]
        rows = [
            {
                normalize_text(key): normalize_text(value)
                for key, value in row.items()
                if key is not None
            }
            for row in reader
        ]
    return headers, rows


def split_destination_codes(raw_header: str) -> list[str]:
    return [
        token
        for token in (
            re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()
            for value in raw_header.split("/")
        )
        if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", token)
    ]


def clean(value: object) -> str:
    return normalize_text(value)
