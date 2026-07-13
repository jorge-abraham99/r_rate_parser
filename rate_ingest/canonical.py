from __future__ import annotations

from rate_ingest.models import CanonicalRate, RateCard, RateOffer


def build_canonical_rates(card: RateCard, offers: list[RateOffer]) -> list[CanonicalRate]:
    canonical_rates: list[CanonicalRate] = []
    for offer in offers:
        if offer.base_amount is None:
            continue
        from_raw = first_present(offer.place_of_receipt, offer.origin, offer.pol)
        to_raw = first_present(offer.final_destination, offer.pod)
        if not from_raw or not to_raw:
            continue
        canonical_rates.append(
            CanonicalRate(
                rate_type=normalize_rate_type(card.document_type),
                from_raw=from_raw,
                to_raw=to_raw,
                amount=offer.base_amount,
                currency=offer.base_currency or card.currency_default,
                unit="per_container",
                valid_from=offer.valid_from or card.valid_from,
                valid_to=offer.valid_to or card.valid_to,
            )
        )
    return canonical_rates


def normalize_rate_type(document_type: str | None) -> str:
    if not document_type:
        return "unknown"
    if document_type.startswith("ocean"):
        return "ocean"
    return document_type


def first_present(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None
