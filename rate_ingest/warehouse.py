from __future__ import annotations

from pathlib import Path

import pandas as pd

from rate_ingest.config import Settings
from rate_ingest.models import CanonicalRate, RateCard, RateChargeLine, RateImport, RateNote, RateOffer
from rate_ingest.utils import append_csv_rows, read_csv_rows, write_csv_rows


def warehouse_paths(settings: Settings) -> dict[str, Path]:
    return {
        "imports": settings.warehouse_dir / "rate_imports.csv",
        "cards": settings.warehouse_dir / "approved_rate_cards.csv",
        "offers": settings.warehouse_dir / "approved_rate_offers.csv",
        "charges": settings.warehouse_dir / "approved_rate_charge_lines.csv",
        "notes": settings.warehouse_dir / "approved_rate_notes.csv",
        "canonical_rates": settings.warehouse_dir / "approved_rates.csv",
    }


def record_import(settings: Settings, rate_import: RateImport) -> None:
    append_csv_rows(warehouse_paths(settings)["imports"], [rate_import.model_dump(mode="json")])


def replace_import(settings: Settings, rate_import: RateImport) -> None:
    path = warehouse_paths(settings)["imports"]
    rows = read_csv_rows(path)
    payload = rate_import.model_dump(mode="json")
    updated = False
    for index, row in enumerate(rows):
        if row.get("id") == rate_import.id:
            rows[index] = {key: str(value) if value is not None else "" for key, value in payload.items()}
            updated = True
            break
    if not updated:
        rows.append({key: str(value) if value is not None else "" for key, value in payload.items()})
    if rows:
        import csv
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def publish_approved_rows(
    settings: Settings,
    cards: list[RateCard],
    offers: list[RateOffer],
    charges: list[RateChargeLine],
    notes: list[RateNote],
    canonical_rates: list[CanonicalRate],
) -> None:
    paths = warehouse_paths(settings)
    append_csv_rows(paths["cards"], [card.model_dump(mode="json") for card in cards])
    append_csv_rows(paths["offers"], [offer.model_dump(mode="json") for offer in offers])
    append_csv_rows(paths["charges"], [charge.model_dump(mode="json") for charge in charges])
    append_csv_rows(paths["notes"], [note.model_dump(mode="json") for note in notes])
    append_csv_rows(paths["canonical_rates"], [rate.model_dump(mode="json") for rate in canonical_rates])


def remove_import_rows(settings: Settings, import_id: str, *, remove_import_record: bool = False) -> None:
    """Remove the warehouse rows published by one import and rebuild canonical rates."""
    paths = warehouse_paths(settings)
    cards = read_csv_rows(paths["cards"])
    removed_card_ids = {row.get("id") for row in cards if row.get("rate_import_id") == import_id}
    kept_cards = [row for row in cards if row.get("rate_import_id") != import_id]

    offers = read_csv_rows(paths["offers"])
    removed_offer_ids = {row.get("id") for row in offers if row.get("rate_card_id") in removed_card_ids}
    kept_offers = [row for row in offers if row.get("rate_card_id") not in removed_card_ids]
    kept_charges = [
        row for row in read_csv_rows(paths["charges"])
        if row.get("rate_offer_id") not in removed_offer_ids
    ]
    kept_notes = [
        row for row in read_csv_rows(paths["notes"])
        if row.get("rate_card_id") not in removed_card_ids and row.get("rate_offer_id") not in removed_offer_ids
    ]

    write_csv_rows(paths["cards"], kept_cards)
    write_csv_rows(paths["offers"], kept_offers)
    write_csv_rows(paths["charges"], kept_charges)
    write_csv_rows(paths["notes"], kept_notes)
    write_csv_rows(paths["canonical_rates"], rebuild_canonical_rows(kept_cards, kept_offers))

    if remove_import_record:
        imports = [row for row in read_csv_rows(paths["imports"]) if row.get("id") != import_id]
        write_csv_rows(paths["imports"], imports)


def rebuild_canonical_rows(cards: list[dict[str, str]], offers: list[dict[str, str]]) -> list[dict[str, object]]:
    cards_by_id = {row.get("id"): row for row in cards}
    canonical_rows: list[dict[str, object]] = []
    for offer in offers:
        card = cards_by_id.get(offer.get("rate_card_id"))
        if not card or not offer.get("base_amount"):
            continue
        from_raw = first_value(offer.get("place_of_receipt"), offer.get("origin"), offer.get("pol"))
        to_raw = first_value(offer.get("final_destination"), offer.get("pod"))
        if not from_raw or not to_raw:
            continue
        document_type = card.get("document_type") or "unknown"
        canonical_rows.append(
            {
                "rate_type": "ocean" if document_type.startswith("ocean") else document_type,
                "from_raw": from_raw,
                "to_raw": to_raw,
                "amount": float(offer["base_amount"]),
                "currency": offer.get("base_currency") or card.get("currency_default"),
                "unit": "per_container",
                "valid_from": offer.get("valid_from") or card.get("valid_from"),
                "valid_to": offer.get("valid_to") or card.get("valid_to"),
            }
        )
    return canonical_rows


def first_value(*values: str | None) -> str | None:
    return next((value for value in values if value), None)


def search_offers(
    settings: Settings,
    provider_name: str | None = None,
    carrier_name: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    equipment_type: str | None = None,
    valid_on: str | None = None,
) -> pd.DataFrame:
    paths = warehouse_paths(settings)
    if not paths["offers"].exists() or not paths["cards"].exists():
        return pd.DataFrame()
    offers = pd.read_csv(paths["offers"])
    cards = pd.read_csv(paths["cards"])
    merged = offers.merge(cards, left_on="rate_card_id", right_on="id", suffixes=("_offer", "_card"))

    if provider_name:
        merged = merged[merged["provider_name"].fillna("").str.contains(provider_name, case=False)]
    if carrier_name:
        merged = merged[merged["carrier_name"].fillna("").str.contains(carrier_name, case=False)]
    if pol:
        merged = merged[merged["pol"].fillna("").str.contains(pol, case=False)]
    if pod:
        merged = merged[merged["pod"].fillna("").str.contains(pod, case=False)]
    if equipment_type:
        merged = merged[merged["equipment_type"].fillna("").str.upper() == equipment_type.upper()]
    if valid_on:
        valid_date = pd.to_datetime(valid_on)
        offer_from = pd.to_datetime(merged["valid_from_offer"], errors="coerce")
        offer_to = pd.to_datetime(merged["valid_to_offer"], errors="coerce")
        card_from = pd.to_datetime(merged["valid_from_card"], errors="coerce")
        card_to = pd.to_datetime(merged["valid_to_card"], errors="coerce")
        starts = offer_from.fillna(card_from)
        ends = offer_to.fillna(card_to)
        merged = merged[(starts.isna() | (starts <= valid_date)) & (ends.isna() | (ends >= valid_date))]
    return merged
