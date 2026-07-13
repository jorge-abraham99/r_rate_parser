from __future__ import annotations

from collections import Counter

from rate_ingest.models import RateCard, RateChargeLine, RateOffer, ValidationItem, ValidationReport


def validate_import(rate_import_id: str, card: RateCard, offers: list[RateOffer], charges: list[RateChargeLine], amount_min: float | None = None, amount_max: float | None = None) -> ValidationReport:
    items: list[ValidationItem] = []
    if not offers:
        items.append(
            ValidationItem(
                severity="ERROR",
                rule_id="no_offers_extracted",
                entity_type="rate_import",
                entity_id=rate_import_id,
                message="Parser produced no usable rate offers.",
            )
        )

    seen = set()
    for offer in offers:
        if not offer.equipment_type:
            items.append(
                ValidationItem(
                    severity="ERROR",
                    rule_id="missing_equipment_type",
                    entity_type="rate_offer",
                    entity_id=offer.id,
                    message="Equipment type is missing.",
                    source_reference=offer.raw_row_reference,
                )
            )
        if offer.base_amount is None and not any(charge.rate_offer_id == offer.id for charge in charges):
            items.append(
                ValidationItem(
                    severity="WARNING",
                    rule_id="missing_amount",
                    entity_type="rate_offer",
                    entity_id=offer.id,
                    message="No base amount was extracted for this offer.",
                    source_reference=offer.raw_row_reference,
                )
            )
        if not offer.base_currency:
            items.append(
                ValidationItem(
                    severity="WARNING",
                    rule_id="missing_currency",
                    entity_type="rate_offer",
                    entity_id=offer.id,
                    message="Currency is missing for this offer.",
                    source_reference=offer.raw_row_reference,
                )
            )
        if card.valid_from and card.valid_to and card.valid_to < card.valid_from:
            items.append(
                ValidationItem(
                    severity="ERROR",
                    rule_id="valid_to_before_valid_from",
                    entity_type="rate_card",
                    entity_id=card.id,
                    message="Rate card validity range is impossible.",
                )
            )
        if amount_min is not None and offer.base_amount is not None and offer.base_amount < amount_min:
            items.append(
                ValidationItem(
                    severity="WARNING",
                    rule_id="amount_outside_template_range",
                    entity_type="rate_offer",
                    entity_id=offer.id,
                    message=f"Amount {offer.base_amount} is below configured template minimum {amount_min}.",
                    source_reference=offer.raw_row_reference,
                )
            )
        if amount_max is not None and offer.base_amount is not None and offer.base_amount > amount_max:
            items.append(
                ValidationItem(
                    severity="WARNING",
                    rule_id="amount_outside_template_range",
                    entity_type="rate_offer",
                    entity_id=offer.id,
                    message=f"Amount {offer.base_amount} is above configured template maximum {amount_max}.",
                    source_reference=offer.raw_row_reference,
                )
            )
        lane_key = (offer.pol, offer.pod, offer.final_destination, offer.equipment_type, offer.valid_from, offer.valid_to)
        lane_key = (
            offer.raw_sheet_name,
            offer.zone,
            offer.pol,
            offer.pod,
            offer.final_destination,
            offer.equipment_type,
            offer.valid_from,
            offer.valid_to,
        )
        if lane_key in seen:
            items.append(
                ValidationItem(
                    severity="WARNING",
                    rule_id="duplicate_offer",
                    entity_type="rate_offer",
                    entity_id=offer.id,
                    message="This lane/equipment/validity combination appears more than once.",
                    source_reference=offer.raw_row_reference,
                )
            )
        seen.add(lane_key)

    counts = Counter(item.severity for item in items)
    return ValidationReport(
        import_id=rate_import_id,
        summary={
            "errors": counts.get("ERROR", 0),
            "warnings": counts.get("WARNING", 0),
            "info": counts.get("INFO", 0),
        },
        items=items,
    )
