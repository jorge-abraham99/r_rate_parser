from __future__ import annotations

from pathlib import Path

import pandas as pd

from rate_ingest.config import Settings
from rate_ingest.models import CanonicalRate, RateCard, RateChargeLine, RateImport, RateNote, RateOffer
from rate_ingest.utils import append_csv_rows, read_csv_rows


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
