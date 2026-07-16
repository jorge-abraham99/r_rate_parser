from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from rate_ingest.approve import approve_import as approve_run
from rate_ingest.approve import reject_import as reject_run
from rate_ingest.canonical import build_canonical_rates
from rate_ingest.classifier import classify_source
from rate_ingest.config import Settings
from rate_ingest.inspector import inspect_source
from rate_ingest.models import RateCard, RateChargeLine, RateImport, RateNote, RateOffer, ValidationReport, new_id
from rate_ingest.parsers.email_table import parse_email as parse_email_table
from rate_ingest.parsers.matrix import parse_workbook as parse_matrix_workbook
from rate_ingest.parsers.offer_block import parse_workbook as parse_offer_block_workbook
from rate_ingest.parsers.tabular_lane import parse_workbook as parse_tabular_workbook
from rate_ingest.review import generate_review_markdown
from rate_ingest.source_registry import register_source
from rate_ingest.template_matcher import find_best_template, load_templates
from rate_ingest.utils import read_csv_rows, read_json, write_csv_rows, write_json
from rate_ingest.validate import validate_import
from rate_ingest.warehouse import record_import, warehouse_paths


def find_run_dir(settings: Settings, import_id: str) -> Path:
    candidate = settings.runs_dir / import_id
    if candidate.exists():
        return candidate
    raise ValueError(f"Run folder not found for import {import_id}")


def deserialize_row(row: dict[str, str]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in row.items():
        if value == "":
            parsed[key] = None
            continue
        if key in {"base_amount", "amount", "classification_confidence"}:
            parsed[key] = float(value)
            continue
        if key.endswith("_json"):
            try:
                parsed[key] = json.loads(value)
            except json.JSONDecodeError:
                parsed[key] = {}
            continue
        parsed[key] = value
    return parsed


def load_run_payload(run_dir: Path) -> dict[str, Any]:
    return {
        "rate_import": read_json(run_dir / "rate_import.json"),
        "source_snapshot": read_json(run_dir / "source_snapshot.json"),
        "detected_structure": read_json(run_dir / "detected_structure.json"),
        "rate_cards": read_csv_rows(run_dir / "parsed_rate_cards.csv"),
        "rate_offers": read_csv_rows(run_dir / "parsed_rate_offers.csv"),
        "rate_charge_lines": read_csv_rows(run_dir / "parsed_rate_charge_lines.csv"),
        "rate_notes": read_csv_rows(run_dir / "parsed_rate_notes.csv"),
        "canonical_rates": read_json(run_dir / "canonical_rates.json"),
        "validation_report": read_json(run_dir / "validation_report.json"),
        "review_markdown": read_review_markdown(run_dir),
        "approval": read_json_if_exists(run_dir / "approval.json"),
    }


def import_source_file(
    settings: Settings,
    source_path: Path,
    template: str | None = None,
    uploaded_by: str | None = None,
) -> dict[str, Any]:
    settings.ensure()
    source = register_source(settings, source_path, uploaded_by=uploaded_by)
    inspected, _ = classify_source(settings, source)
    scored = inspected.possible_templates
    if template:
        matched_template = next((item for item in load_templates(settings) if item.template_id == template), None)
    else:
        matched_template, scored = find_best_template(settings, inspected)

    if not matched_template:
        raise ValueError("No matching parser template found. Use inspect output to add a template.")

    rate_import = RateImport(
        id=new_id("import"),
        source_document_id=source.id,
        parser_family=matched_template.parser_family,
        template_id=matched_template.template_id,
        classification_confidence=next(
            (item["confidence"] for item in scored if item["template_id"] == matched_template.template_id),
            None,
        ),
        status="pending_review",
    )
    run_dir = settings.runs_dir / rate_import.id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "source_snapshot.json", source.model_dump(mode="json"))
    write_json(run_dir / "detected_structure.json", inspected.model_dump(mode="json"))

    card, offers, charges, notes = parse_source_by_family(
        Path(source.source_path),
        matched_template.parser_family,
        matched_template,
        rate_import,
    )
    validation = validate_import(
        rate_import.id,
        card,
        offers,
        charges,
        amount_min=matched_template.validation.get("amount_min"),
        amount_max=matched_template.validation.get("amount_max"),
    )
    if validation.summary.get("errors", 0) > 0:
        rate_import.status = "failed"
    rate_import.validation_summary_json = validation.model_dump(mode="json")["summary"]

    canonical_rates = build_canonical_rates(card, offers)
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    write_csv_rows(run_dir / "parsed_rate_cards.csv", [card.model_dump(mode="json")])
    write_csv_rows(run_dir / "parsed_rate_offers.csv", [offer.model_dump(mode="json") for offer in offers])
    write_csv_rows(run_dir / "parsed_rate_charge_lines.csv", [charge.model_dump(mode="json") for charge in charges])
    write_csv_rows(run_dir / "parsed_rate_notes.csv", [note.model_dump(mode="json") for note in notes])
    write_json(run_dir / "canonical_rates.json", [rate.model_dump(mode="json") for rate in canonical_rates])
    write_json(run_dir / "validation_report.json", validation.model_dump(mode="json"))
    review_path = generate_review_markdown(
        run_dir,
        rate_import,
        source.file_name,
        matched_template.template_name,
        card,
        offers,
        charges,
        notes,
        validation,
    )
    record_import(settings, rate_import)

    return {
        "import_id": rate_import.id,
        "rate_import": rate_import.model_dump(mode="json"),
        "source": source.model_dump(mode="json"),
        "detected_structure": inspected.model_dump(mode="json"),
        "template_id": matched_template.template_id,
        "template_name": matched_template.template_name,
        "parser_family": matched_template.parser_family,
        "counts": {
            "rate_cards": 1,
            "rate_offers": len(offers),
            "charge_lines": len(charges),
            "notes": len(notes),
            "canonical_rates": len(canonical_rates),
        },
        "validation_summary": validation.summary,
        "review_path": str(review_path),
    }


def get_import_detail(settings: Settings, import_id: str) -> dict[str, Any]:
    run_dir = find_run_dir(settings, import_id)
    payload = load_run_payload(run_dir)
    rate_import = RateImport(**payload["rate_import"])
    cards = [RateCard(**deserialize_row(row)) for row in payload["rate_cards"]]
    offers = [RateOffer(**deserialize_row(row)) for row in payload["rate_offers"]]
    charges = [RateChargeLine(**deserialize_row(row)) for row in payload["rate_charge_lines"]]
    notes = [RateNote(**deserialize_row(row)) for row in payload["rate_notes"]]
    card = cards[0] if cards else None
    return {
        "import_id": import_id,
        "rate_import": rate_import.model_dump(mode="json"),
        "source": payload["source_snapshot"],
        "detected_structure": payload["detected_structure"],
        "summary": {
            "rate_cards": len(cards),
            "rate_offers": len(offers),
            "charge_lines": len(charges),
            "notes": len(notes),
            "canonical_rates": len(payload["canonical_rates"]),
        },
        "validation_report": payload["validation_report"],
        "approval": payload["approval"],
        "review_markdown": payload["review_markdown"],
        "card": card.model_dump(mode="json") if card else None,
        "offers_preview": [offer.model_dump(mode="json") for offer in offers[:50]],
        "charges_preview": [charge.model_dump(mode="json") for charge in charges[:50]],
        "notes_preview": [note.model_dump(mode="json") for note in notes[:30]],
        "canonical_rates": payload["canonical_rates"],
    }


def list_imports(settings: Settings, limit: int = 50) -> list[dict[str, Any]]:
    rows = read_csv_rows(warehouse_paths(settings)["imports"])
    imports: list[dict[str, Any]] = []
    for row in rows:
        item = RateImport(**deserialize_row(row))
        run_dir = settings.runs_dir / item.id
        source_snapshot = read_json_if_exists(run_dir / "source_snapshot.json") or {}
        validation_report = read_json_if_exists(run_dir / "validation_report.json") or {"summary": {}}
        imports.append(
            {
                "import_id": item.id,
                "status": item.status,
                "parser_family": item.parser_family,
                "template_id": item.template_id,
                "classification_confidence": item.classification_confidence,
                "approved_by": item.approved_by,
                "approved_at": serialize_date(item.approved_at),
                "created_at": serialize_date(item.created_at),
                "file_name": source_snapshot.get("file_name"),
                "source_type": source_snapshot.get("source_type"),
                "validation_summary": validation_report.get("summary", item.validation_summary_json),
            }
        )
    imports.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return imports[:limit]


def approve_import_by_id(settings: Settings, import_id: str, approved_by: str) -> dict[str, Any]:
    run_dir = find_run_dir(settings, import_id)
    payload = load_run_payload(run_dir)
    rate_import = RateImport(**payload["rate_import"])
    validation_report = ValidationReport(**payload["validation_report"])
    cards = [RateCard(**deserialize_row(row)) for row in payload["rate_cards"]]
    offers = [RateOffer(**deserialize_row(row)) for row in payload["rate_offers"]]
    charges = [RateChargeLine(**deserialize_row(row)) for row in payload["rate_charge_lines"]]
    notes = [RateNote(**deserialize_row(row)) for row in payload["rate_notes"]]
    approve_run(settings, run_dir, rate_import, validation_report, cards, offers, charges, notes, approved_by)
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    return get_import_detail(settings, import_id)


def reject_import_by_id(settings: Settings, import_id: str, reason: str) -> dict[str, Any]:
    run_dir = find_run_dir(settings, import_id)
    rate_import = RateImport(**read_json(run_dir / "rate_import.json"))
    reject_run(settings, run_dir, rate_import, reason)
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    return get_import_detail(settings, import_id)


def search_approved_offers(
    settings: Settings,
    provider_name: str | None = None,
    carrier_name: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    equipment_type: str | None = None,
    valid_on: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    paths = warehouse_paths(settings)
    cards = [RateCard(**deserialize_row(row)) for row in read_csv_rows(paths["cards"])]
    offers = [RateOffer(**deserialize_row(row)) for row in read_csv_rows(paths["offers"])]
    charges = [RateChargeLine(**deserialize_row(row)) for row in read_csv_rows(paths["charges"])]
    notes = [RateNote(**deserialize_row(row)) for row in read_csv_rows(paths["notes"])]

    cards_by_id = {card.id: card for card in cards}
    charges_by_offer: dict[str, list[RateChargeLine]] = {}
    for charge in charges:
        charges_by_offer.setdefault(charge.rate_offer_id, []).append(charge)
    notes_by_offer: dict[str, list[RateNote]] = {}
    notes_by_card: dict[str, list[RateNote]] = {}
    for note in notes:
        if note.rate_offer_id:
            notes_by_offer.setdefault(note.rate_offer_id, []).append(note)
        notes_by_card.setdefault(note.rate_card_id, []).append(note)

    valid_on_date = parse_iso_date(valid_on) if valid_on else None
    results: list[dict[str, Any]] = []
    for offer in offers:
        card = cards_by_id.get(offer.rate_card_id)
        if not card:
            continue
        if provider_name and not contains_text(card.provider_name, provider_name):
            continue
        if carrier_name and not contains_text(card.carrier_name, carrier_name):
            continue
        if pol and not contains_text(offer.pol, pol):
            continue
        if pod and not contains_text(first_present(offer.pod, offer.final_destination), pod):
            continue
        if equipment_type and (offer.equipment_type or "").upper() != equipment_type.upper():
            continue
        if valid_on_date and not offer_valid_on(offer, card, valid_on_date):
            continue

        offer_charges = charges_by_offer.get(offer.id, [])
        note_bucket = notes_by_offer.get(offer.id) or notes_by_card.get(card.id, [])
        charge_total = round(sum(charge.amount or 0 for charge in offer_charges), 2)
        if offer.base_amount is None and charge_total == 0:
            all_in_amount = None
        elif offer.all_in_flag is True or not offer_charges:
            all_in_amount = offer.base_amount
        else:
            all_in_amount = round((offer.base_amount or 0) + charge_total, 2)
        results.append(
            {
                "offer_id": offer.id,
                "rate_card_id": offer.rate_card_id,
                "provider_name": card.provider_name,
                "carrier_name": card.carrier_name,
                "document_type": card.document_type,
                "commodity": card.commodity,
                "origin": offer.origin,
                "place_of_receipt": offer.place_of_receipt,
                "pol": offer.pol,
                "pod": offer.pod,
                "final_destination": offer.final_destination,
                "equipment_type": offer.equipment_type,
                "base_amount": offer.base_amount,
                "base_currency": offer.base_currency or card.currency_default,
                "all_in_amount": all_in_amount,
                "all_in_flag": offer.all_in_flag,
                "charge_total": charge_total if offer_charges else None,
                "valid_from": serialize_date(offer.valid_from or card.valid_from),
                "valid_to": serialize_date(offer.valid_to or card.valid_to),
                "raw_sheet_name": offer.raw_sheet_name,
                "raw_row_reference": offer.raw_row_reference,
                "routing_note": offer.routing_note,
                "notes_summary": note_bucket[0].note_text if note_bucket else card.notes_summary,
                "charges": [charge.model_dump(mode="json") for charge in offer_charges],
                "notes": [note.model_dump(mode="json") for note in note_bucket[:10]],
            }
        )
    results.sort(key=lambda item: ((item["all_in_amount"] is None), item["all_in_amount"] or 0, item["carrier_name"] or ""))
    return results[:limit]


def parse_source_by_family(
    source_path: Path,
    parser_family: str,
    matched_template,
    rate_import: RateImport,
):
    if parser_family == "tabular_lane":
        return parse_tabular_workbook(source_path, matched_template, rate_import)
    if parser_family == "matrix":
        return parse_matrix_workbook(source_path, matched_template, rate_import)
    if parser_family == "offer_block":
        return parse_offer_block_workbook(source_path, matched_template, rate_import)
    if parser_family == "email_table":
        return parse_email_table(source_path, matched_template, rate_import)
    raise ValueError(f"Template {matched_template.template_id} uses unsupported parser family {parser_family}.")


def read_review_markdown(run_dir: Path) -> str | None:
    path = run_dir / "review.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return read_json(path)


def contains_text(value: str | None, search: str) -> bool:
    return search.lower() in (value or "").lower()


def offer_valid_on(offer: RateOffer, card: RateCard, valid_on: date) -> bool:
    start = offer.valid_from or card.valid_from
    end = offer.valid_to or card.valid_to
    if start and start > valid_on:
        return False
    if end and end < valid_on:
        return False
    return True


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def serialize_date(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def first_present(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None
