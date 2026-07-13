from __future__ import annotations

from pathlib import Path

from rate_ingest.models import RateCard, RateChargeLine, RateImport, RateNote, RateOffer, ValidationReport


def generate_review_markdown(
    run_dir: Path,
    rate_import: RateImport,
    source_file_name: str,
    template_name: str | None,
    card: RateCard,
    offers: list[RateOffer],
    charges: list[RateChargeLine],
    notes: list[RateNote],
    validation: ValidationReport,
) -> Path:
    path = run_dir / "review.md"
    lines = [
        f"# Import Review: {rate_import.id}",
        "",
        "## Source",
        f"- File: {source_file_name}",
        f"- Provider: {card.provider_name or '-'}",
        "",
        "## Parser",
        f"- Parser family: {rate_import.parser_family}",
        f"- Template: {template_name or 'auto/unknown'}",
        f"- Classification confidence: {rate_import.classification_confidence or '-'}",
        "",
        "## Extraction Summary",
        f"- Rate cards: 1",
        f"- Rate offers: {len(offers)}",
        f"- Charge lines: {len(charges)}",
        f"- Notes: {len(notes)}",
        "",
        "## Validation Summary",
        f"- Errors: {validation.summary.get('errors', 0)}",
        f"- Warnings: {validation.summary.get('warnings', 0)}",
        f"- Info: {validation.summary.get('info', 0)}",
        "",
        "## Validation Items",
        "| Severity | Rule | Message | Source |",
        "|---|---|---|---|",
    ]
    for item in validation.items:
        lines.append(f"| {item.severity} | {item.rule_id} | {item.message} | {item.source_reference or '-'} |")

    lines.extend([
        "",
        "## Rate Offer Preview",
        "| POL | POD | Destination | Equipment | Base Amount | Currency | Valid From | Valid To | Source |",
        "|---|---|---|---|---:|---|---|---|---|",
    ])
    for offer in offers[:30]:
        lines.append(
            f"| {offer.pol or '-'} | {offer.pod or '-'} | {offer.final_destination or '-'} | {offer.equipment_type} | "
            f"{offer.base_amount if offer.base_amount is not None else '-'} | {offer.base_currency or '-'} | "
            f"{offer.valid_from or card.valid_from or '-'} | {offer.valid_to or card.valid_to or '-'} | {offer.raw_row_reference or '-'} |"
        )

    if charges:
        lines.extend([
            "",
            "## Charge Line Preview",
            "| Offer ID | Charge | Amount | Currency | Source |",
            "|---|---|---:|---|---|",
        ])
        for charge in charges[:30]:
            lines.append(f"| {charge.rate_offer_id} | {charge.charge_name} | {charge.amount or '-'} | {charge.currency or '-'} | {charge.source_label or '-'} |")

    if notes:
        lines.extend([
            "",
            "## Notes Preview",
            "| Type | Text | Source |",
            "|---|---|---|",
        ])
        for note in notes[:20]:
            lines.append(f"| {note.note_type} | {note.note_text.replace('|', '/')} | {note.source_reference or '-'} |")

    lines.extend([
        "",
        "## Approval Decision",
        f"- Approve command: `python -m rate_ingest approve {rate_import.id} --approved-by <name>`",
        f"- Reject command: `python -m rate_ingest reject {rate_import.id} --reason \"<reason>\"`",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path

