from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timezone
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
from rate_ingest.parsers.cosco_pdf_quote import parse_pdf as parse_cosco_pdf_quote
from rate_ingest.parsers.hapag_door_matrix import parse_workbook as parse_hapag_door_matrix_workbook
from rate_ingest.parsers.haulage_matrix import parse_workbook as parse_haulage_matrix_workbook
from rate_ingest.parsers.matrix import parse_workbook as parse_matrix_workbook
from rate_ingest.parsers.msc_zoned_inline import extract_tier_rate_tables
from rate_ingest.parsers.msc_zoned_inline import parse_workbook as parse_msc_zoned_inline_workbook
from rate_ingest.parsers.offer_block import parse_workbook as parse_offer_block_workbook
from rate_ingest.parsers.site_to_site_rows import parse_workbook as parse_site_to_site_workbook
from rate_ingest.parsers.tabular_lane import parse_workbook as parse_tabular_workbook
from rate_ingest.review import generate_review_markdown
from rate_ingest.repositories import (
    LOCAL_CSV_ORGANIZATION_ID,
    OrganizationId,
    RateRepository,
    get_rate_repository,
)
from rate_ingest.template_matcher import find_best_template, load_templates
from rate_ingest.utils import read_csv_rows, read_json, write_csv_rows, write_json
from rate_ingest.validate import validate_import

FX_RATES = {
    "USD": 1.0,
    "GBP": 1.29,
    "EUR": 1.09,
    "INR": 0.0104,
    "THB": 0.0302,
}

BILL_OF_LADING_BASES = {"bill of lading", "b/l", "bl", "booking"}


def resolve_repository_organization_id(
    settings: Settings,
    organization_id: OrganizationId | None,
) -> OrganizationId:
    if organization_id is not None and str(organization_id).strip():
        return organization_id
    if settings.rate_storage_backend == "csv":
        return LOCAL_CSV_ORGANIZATION_ID
    raise ValueError("organization_id is required for Postgres rate storage")


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
        "tier_rate_tables": read_json_if_exists(run_dir / "tier_rate_tables.json") or {},
        "review_markdown": read_review_markdown(run_dir),
        "approval": read_json_if_exists(run_dir / "approval.json"),
    }


def import_source_file(
    settings: Settings,
    source_path: Path,
    template: str | None = None,
    uploaded_by: str | None = None,
    source_file_name: str | None = None,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    settings.ensure()
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    source = rate_repository.register_source_document(
        source_path,
        organization_id=repository_org_id,
        uploaded_by=uploaded_by,
    )
    if source_file_name:
        source.file_name = Path(source_file_name).name
    inspected, _ = classify_source(settings, source)
    scored = inspected.possible_templates
    if template:
        matched_template = next((item for item in load_templates(settings) if item.template_id == template), None)
    else:
        matched_template, scored = find_best_template(settings, inspected)

    if not matched_template:
        best = scored[0] if scored else None
        best_detail = (
            f" Best candidate: {best['template_id']} ({best['confidence']:.2f})."
            if best
            else " No active templates were found."
        )
        raise ValueError(
            "No matching parser template found."
            f" Detected type={inspected.workbook_type}, provider={inspected.provider_guess or 'unknown'},"
            f" parser={inspected.parser_family_guess or 'unknown'}."
            f"{best_detail}"
        )

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
    if matched_template.parser_family == "msc_zoned_inline":
        write_json(run_dir / "tier_rate_tables.json", extract_tier_rate_tables(Path(source.source_path), matched_template))
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
    rate_repository.add_import(rate_import, organization_id=repository_org_id)

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
    charge_bucket_summary = analyze_charge_collection(
        charges,
        base_currency=card.currency_default if card else None,
    )
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
        "charge_bucket_summary": summarize_charge_analysis(charge_bucket_summary),
        "tier_rate_tables": payload["tier_rate_tables"],
        "offers_preview": [offer.model_dump(mode="json") for offer in offers[:50]],
        "charges_preview": [charge.model_dump(mode="json") for charge in charges[:50]],
        "notes_preview": [note.model_dump(mode="json") for note in notes[:30]],
        "canonical_rates": payload["canonical_rates"],
    }


def list_imports(
    settings: Settings,
    limit: int = 50,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> list[dict[str, Any]]:
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    imports: list[dict[str, Any]] = []
    for item in rate_repository.list_import_records(organization_id=repository_org_id):
        run_dir = settings.runs_dir / item.id
        source_snapshot = read_json_if_exists(run_dir / "source_snapshot.json") or {}
        validation_report = read_json_if_exists(run_dir / "validation_report.json") or {"summary": {}}
        card_rows = read_csv_rows(run_dir / "parsed_rate_cards.csv")
        offer_rows = read_csv_rows(run_dir / "parsed_rate_offers.csv")
        card = card_rows[0] if card_rows else {}
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
                "uploaded_by": source_snapshot.get("uploaded_by"),
                "carrier_name": card.get("carrier_name") or card.get("provider_name"),
                "carrier_key": source_snapshot.get("operator_carrier_key"),
                "carrier_label": source_snapshot.get("operator_carrier_label"),
                "contract_tag": source_snapshot.get("contract_tag"),
                "valid_from": card.get("valid_from"),
                "valid_to": card.get("valid_to"),
                "lane_count": len(offer_rows),
                "validation_summary": validation_report.get("summary", item.validation_summary_json),
            }
        )
    imports.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return imports[:limit]


def approve_import_by_id(
    settings: Settings,
    import_id: str,
    approved_by: str,
    *,
    carrier_name: str | None = None,
    carrier_key: str | None = None,
    carrier_label: str | None = None,
    contract_tag: str | None = None,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    run_dir = find_run_dir(settings, import_id)
    payload = load_run_payload(run_dir)
    rate_import = RateImport(**payload["rate_import"])
    validation_report = ValidationReport(**payload["validation_report"])
    cards = [RateCard(**deserialize_row(row)) for row in payload["rate_cards"]]
    offers = [RateOffer(**deserialize_row(row)) for row in payload["rate_offers"]]
    charges = [RateChargeLine(**deserialize_row(row)) for row in payload["rate_charge_lines"]]
    notes = [RateNote(**deserialize_row(row)) for row in payload["rate_notes"]]
    if validation_report.summary.get("errors", 0) > 0:
        raise ValueError("Import has blocking validation errors and cannot be approved.")
    if carrier_name and cards:
        cards[0].carrier_name = carrier_name
        cards[0].provider_name = carrier_name
        write_csv_rows(run_dir / "parsed_rate_cards.csv", [card.model_dump(mode="json") for card in cards])
    if carrier_key or carrier_label or contract_tag:
        source_snapshot = payload["source_snapshot"]
        source_snapshot["operator_carrier_key"] = carrier_key
        source_snapshot["operator_carrier_label"] = carrier_label or carrier_name
        source_snapshot["contract_tag"] = contract_tag
        write_json(run_dir / "source_snapshot.json", source_snapshot)
    if carrier_key:
        archive_previous_imports(
            settings,
            carrier_key,
            excluding=import_id,
            repository=rate_repository,
            organization_id=repository_org_id,
        )
    approve_run(
        settings,
        run_dir,
        rate_import,
        validation_report,
        cards,
        offers,
        charges,
        notes,
        approved_by,
        repository=rate_repository,
        organization_id=repository_org_id,
    )
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    return get_import_detail(settings, import_id)


def reject_import_by_id(
    settings: Settings,
    import_id: str,
    reason: str,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    run_dir = find_run_dir(settings, import_id)
    rate_import = RateImport(**read_json(run_dir / "rate_import.json"))
    reject_run(
        settings,
        run_dir,
        rate_import,
        reason,
        repository=rate_repository,
        organization_id=repository_org_id,
    )
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    return get_import_detail(settings, import_id)


def delete_import_by_id(
    settings: Settings,
    import_id: str,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    run_dir = find_run_dir(settings, import_id)
    rate_repository.remove_import_data(
        import_id,
        organization_id=repository_org_id,
        remove_import_record=True,
    )
    shutil.rmtree(run_dir)
    return {"deleted": True, "import_id": import_id}


def archive_previous_imports(
    settings: Settings,
    carrier_key: str,
    *,
    excluding: str,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> None:
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    for item in list_imports(
        settings,
        limit=5000,
        repository=rate_repository,
        organization_id=repository_org_id,
    ):
        if item["import_id"] == excluding or item.get("status") != "approved":
            continue
        if item.get("carrier_key") != carrier_key:
            continue
        previous_dir = find_run_dir(settings, item["import_id"])
        previous = RateImport(**read_json(previous_dir / "rate_import.json"))
        rate_repository.remove_import_data(
            previous.id,
            organization_id=repository_org_id,
        )
        previous.status = "archived"
        write_json(previous_dir / "rate_import.json", previous.model_dump(mode="json"))
        rate_repository.update_import(previous, organization_id=repository_org_id)


def search_approved_offers(
    settings: Settings,
    provider_name: str | None = None,
    carrier_name: str | None = None,
    collection: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    equipment_type: str | None = None,
    valid_on: str | None = None,
    limit: int = 200,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> list[dict[str, Any]]:
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    library = rate_repository.load_approved_rate_library(
        organization_id=repository_org_id,
    )
    cards = library.cards
    offers = library.offers
    charges = library.charges
    notes = library.notes

    cards_by_id = {card.id: card for card in cards}
    source_by_import = library.source_by_import
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
        if collection and not contains_text(first_present(offer.place_of_receipt, offer.origin), collection):
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
        charge_analysis = analyze_charge_collection(
            offer_charges,
            base_currency=offer.base_currency or card.currency_default,
            base_amount=offer.base_amount,
            base_label=base_charge_label(offer),
        )
        additive_charges = [
            charge for charge in offer_charges
            if not is_base_charge(charge)
            and currencies_match(charge.currency, offer.base_currency or card.currency_default)
        ]
        charge_total = round(sum(charge.amount or 0 for charge in additive_charges), 2)
        if offer.base_amount is None and charge_total == 0:
            all_in_amount = None
        elif offer.all_in_flag is True or not offer_charges:
            all_in_amount = offer.base_amount
        else:
            all_in_amount = round((offer.base_amount or 0) + charge_total, 2)
        source_payload = source_by_import.get(card.rate_import_id, {})
        offer_commodity = offer.commodity or card.commodity
        materials = infer_materials(
            offer_commodity,
            source_payload.get("operator_carrier_key"),
            source_payload.get("file_name"),
            offer.raw_sheet_name,
        )
        results.append(
            {
                "offer_id": offer.id,
                "rate_card_id": offer.rate_card_id,
                "provider_name": card.provider_name,
                "carrier_name": card.carrier_name,
                "document_type": card.document_type,
                "commodity": offer_commodity,
                "origin": offer.origin,
                "place_of_receipt": offer.place_of_receipt,
                "pol": offer.pol,
                "pod": offer.pod,
                "final_destination": offer.final_destination,
                "equipment_type": offer.equipment_type,
                "service_mode": offer.service_mode,
                "transit_time_days": offer.transit_time_days,
                "base_amount": offer.base_amount,
                "base_currency": offer.base_currency or card.currency_default,
                "all_in_amount": all_in_amount,
                "all_in_usd": charge_analysis["total_usd"],
                "all_in_flag": offer.all_in_flag,
                "charge_total": charge_total if offer_charges else None,
                "valid_from": serialize_date(offer.valid_from or card.valid_from),
                "valid_to": serialize_date(offer.valid_to or card.valid_to),
                "raw_sheet_name": offer.raw_sheet_name,
                "source_file_name": source_payload.get("file_name"),
                "carrier_key": source_payload.get("operator_carrier_key"),
                "carrier_label": source_payload.get("operator_carrier_label"),
                "contract_tag": source_payload.get("contract_tag"),
                "materials": materials,
                "offer_reference": offer.offer_reference,
                "raw_row_reference": offer.raw_row_reference,
                "routing_note": offer.routing_note,
                "charge_analysis": charge_analysis,
                "notes_summary": note_bucket[0].note_text if note_bucket else card.notes_summary,
                "charges": [charge.model_dump(mode="json") for charge in offer_charges],
                "notes": [note.model_dump(mode="json") for note in note_bucket[:10]],
            }
        )
    results.sort(
        key=lambda item: (
            item["all_in_usd"] is None,
            item["all_in_usd"] if item["all_in_usd"] is not None else float("inf"),
            item["carrier_name"] or "",
        )
    )
    return results[:limit]


def get_rate_desk_data(
    settings: Settings,
    limit: int = 2000,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = repository if repository is not None else get_rate_repository(settings)
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    all_rates = search_approved_offers(
        settings,
        limit=max(limit * 20, 50000),
        repository=rate_repository,
        organization_id=repository_org_id,
    )
    haulage_rates = [rate for rate in all_rates if is_haulage_rate(rate)]
    quote_rates = [rate for rate in all_rates if not is_haulage_rate(rate)]
    rates = quote_rates[:limit]
    imports = list_imports(
        settings,
        limit=500,
        repository=rate_repository,
        organization_id=repository_org_id,
    )
    approved_at = [item.get("approved_at") for item in imports if item.get("approved_at")]
    last_refreshed = max(approved_at, key=parse_datetime_sort_key) if approved_at else None

    origin_map: dict[str, str] = {}
    dest_map: dict[str, str] = {}
    collection_map: dict[str, str] = {}
    for rate in quote_rates:
        val = first_present(rate.get("place_of_receipt"), rate.get("origin"))
        if val:
            collection_map.setdefault(normalize_location_key(val), val)
        val = first_present(rate.get("pol"), rate.get("place_of_receipt"), rate.get("origin"))
        if val:
            origin_map.setdefault(normalize_location_key(val), val)
        val = first_present(rate.get("final_destination"), rate.get("pod"))
        if val:
            dest_map.setdefault(normalize_location_key(val), val)
    origins = sorted(origin_map.values())
    destinations = sorted(dest_map.values())
    collections = sorted(collection_map.values())
    equipment_types = sorted({rate["equipment_type"] for rate in quote_rates if rate.get("equipment_type")})
    carriers = sorted(
        {
            first_present(rate.get("carrier_name"), rate.get("provider_name"))
            for rate in quote_rates
            if first_present(rate.get("carrier_name"), rate.get("provider_name"))
        }
    )
    materials = sorted({material for rate in quote_rates for material in rate.get("materials", [])})
    haulage_tariffs, door_pickups, haulage_currency = build_haulage_lookup(haulage_rates)
    return {
        "last_refreshed": last_refreshed,
        "rates": rates,
        "haulage_tariffs": haulage_tariffs,
        "haulage_currency": haulage_currency,
        "filters": {
            "origins": origins,
            "destinations": destinations,
            "collection_places": collections,
            "equipment_types": equipment_types,
            "carriers": carriers,
            "materials": materials,
            "door_pickups": door_pickups,
        },
    }


def analyze_charge_collection(
    charges: list[RateChargeLine],
    *,
    base_currency: str | None = None,
    base_amount: float | None = None,
    base_label: str = "Basic Ocean Freight",
) -> dict[str, Any]:
    grouped = {
        "origin": {"key": "origin", "label": "Origin charges", "lines": [], "subtotal_usd": 0.0},
        "freight": {"key": "freight", "label": "Freight charges", "lines": [], "subtotal_usd": 0.0},
        "destination": {"key": "destination", "label": "Destination charges", "lines": [], "subtotal_usd": 0.0},
        "unmatched": {"key": "unmatched", "label": "Unmatched charges", "lines": [], "subtotal_usd": 0.0},
    }
    matched_count = 0
    unmatched_count = 0

    has_base_line = any(is_base_charge(charge) for charge in charges)
    if charges:
        for charge in charges:
            bucket, matched_by = classify_charge_bucket(charge)
            usd_unit_amount = convert_to_usd(charge.amount, charge.currency or base_currency)
            line = {
                "name": charge.charge_name,
                "basis": charge.basis or "Container",
                "quantity_rule": quantity_rule(charge.basis),
                "currency": (charge.currency or base_currency or "USD").upper(),
                "unit_amount": charge.amount,
                "usd_unit_amount": usd_unit_amount,
                "charge_type": charge.charge_type,
                "bucket": bucket,
                "matched_by": matched_by,
                "zero_rated": (charge.amount or 0) == 0,
            }
            grouped[bucket]["lines"].append(line)
            grouped[bucket]["subtotal_usd"] += usd_unit_amount
            if bucket == "unmatched":
                unmatched_count += 1
            else:
                matched_count += 1
    if base_amount is not None and not has_base_line:
        usd_unit_amount = convert_to_usd(base_amount, base_currency)
        grouped["freight"]["lines"].append(
            {
                "name": base_label,
                "basis": "Container",
                "quantity_rule": "per_container",
                "currency": (base_currency or "USD").upper(),
                "unit_amount": base_amount,
                "usd_unit_amount": usd_unit_amount,
                "charge_type": "freight",
                "bucket": "freight",
                "matched_by": "synthetic_base",
                "zero_rated": (base_amount or 0) == 0,
            }
        )
        grouped["freight"]["subtotal_usd"] += usd_unit_amount
        matched_count += 1

    ordered_groups = []
    total_usd = 0.0
    for key in ("origin", "freight", "destination"):
        group = grouped[key]
        subtotal = round(group["subtotal_usd"], 2)
        ordered_groups.append(
            {
                "key": key,
                "label": group["label"],
                "lines": group["lines"],
                "line_count": len(group["lines"]),
                "zero_line_count": sum(1 for line in group["lines"] if line["zero_rated"]),
                "subtotal_usd": subtotal,
            }
        )
        total_usd += group["subtotal_usd"]

    unmatched_group = grouped["unmatched"]
    return {
        "fx_source": "static_demo_fx_v1",
        "groups": ordered_groups,
        "unmatched_lines": unmatched_group["lines"],
        "matched_charge_count": matched_count,
        "unmatched_charge_count": unmatched_count,
        "unmatched_subtotal_usd": round(unmatched_group["subtotal_usd"], 2),
        "total_usd": round(total_usd + unmatched_group["subtotal_usd"], 2),
    }


def summarize_charge_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in analysis.items() if key not in {"groups", "unmatched_lines"}},
        "groups": [
            {key: value for key, value in group.items() if key != "lines"}
            for group in analysis.get("groups", [])
        ],
    }


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
    if parser_family == "haulage_matrix":
        return parse_haulage_matrix_workbook(source_path, matched_template, rate_import)
    if parser_family == "msc_zoned_inline":
        return parse_msc_zoned_inline_workbook(source_path, matched_template, rate_import)
    if parser_family == "hapag_door_matrix":
        return parse_hapag_door_matrix_workbook(source_path, matched_template, rate_import)
    if parser_family == "cosco_pdf_quote":
        return parse_cosco_pdf_quote(source_path, matched_template, rate_import)
    if parser_family == "offer_block":
        return parse_offer_block_workbook(source_path, matched_template, rate_import)
    if parser_family == "site_to_site_rows":
        return parse_site_to_site_workbook(source_path, matched_template, rate_import)
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


def infer_materials(
    commodity: str | None,
    carrier_key: str | None,
    source_file_name: str | None,
    sheet_name: str | None,
) -> list[str]:
    text = " ".join(filter(None, [commodity, carrier_key, source_file_name, sheet_name])).lower()
    materials: list[str] = []
    if "paper" in text or "peute" in text:
        materials.append("Paper")
    if any(token in text for token in ["metal", "scrap", "steel"]):
        materials.append("Metal")
    if any(token in text for token in ["tyre", "tire", "rubber"]):
        materials.append("Tyres")
    return materials


def is_haulage_rate(rate: dict[str, Any]) -> bool:
    # Only standalone inland tariffs belong in the merchant-haulage lookup.
    # Carrier door-to-quay products, including MSC SD / CY, remain quote rates.
    document_type = str(rate.get("document_type") or "").lower()
    carrier_key = str(rate.get("carrier_key") or "").lower()
    contract_tag = str(rate.get("contract_tag") or "").upper()
    return document_type == "inland_export" or carrier_key == "haulage-q2" or contract_tag == "HAUL"


def normalize_location_key(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[,\s]+(?:gb|uk)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_haulage_lookup(haulage_rates: list[dict[str, Any]]) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]], str | None]:
    pickups: dict[str, dict[str, Any]] = {}
    tariffs: dict[str, dict[str, float]] = {}
    haulage_currency: str | None = None
    for rate in haulage_rates:
        collection = first_present(rate.get("place_of_receipt"), rate.get("origin"))
        port = first_present(rate.get("pol"), rate.get("final_destination"), rate.get("pod"))
        amount = rate.get("base_amount")
        currency = (rate.get("base_currency") or "").upper()
        if currency and haulage_currency is None:
            haulage_currency = currency
        if not collection:
            continue
        key = normalize_location_key(collection)
        display_name = pickups.get(key, {}).get("name", collection)
        pickups.setdefault(
            key,
            {
                "name": display_name,
                "valid_from": rate.get("valid_from"),
                "valid_to": rate.get("valid_to"),
                "source_file_name": rate.get("source_file_name"),
            },
        )
        if not port or amount is None:
            continue
        if haulage_currency and currency and currency != haulage_currency:
            continue
        tariffs.setdefault(key, {})[normalize_location_key(port)] = round(float(amount), 2)
    return tariffs, sorted(pickups.values(), key=lambda item: item["name"]), haulage_currency


def is_base_charge(charge: RateChargeLine) -> bool:
    if (charge.charge_type or "").lower() == "base":
        return True
    name = (charge.charge_name or "").lower()
    return "basic ocean freight" in name or name == "ocean freight"


def currencies_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    return left.upper() == right.upper()


def parse_datetime_sort_key(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


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


def base_charge_label(offer: RateOffer) -> str:
    service_mode = (offer.service_mode or "").strip().lower().replace("-", "/")
    if service_mode in {"sd / cy", "sd/cy"} or service_mode.startswith("sd "):
        return "Door-to-quay rate as quoted"
    if offer.all_in_flag is True:
        return "All-in as quoted"
    return "Basic Ocean Freight"


def classify_charge_bucket(charge: RateChargeLine) -> tuple[str, str]:
    charge_type = (charge.charge_type or "").strip().lower()
    if charge_type in {"origin", "freight", "destination"}:
        return charge_type, "explicit_charge_type"

    name = (charge.charge_name or "").strip().lower()
    if is_base_charge(charge):
        return "freight", "base_charge"
    if any(token in name for token in ("origin", "export", "haulage", "intermodal", "pickup", "inland", "rail", "truck")):
        return "origin", "heuristic_name"
    if any(token in name for token in ("destination", "import", "terminal handling", "documentation", "documentation fee", "container protect", "delivery", "dthc")):
        return "destination", "heuristic_name"
    if any(token in name for token in ("bunker", "ocean freight", "emission", "peak season", "contingency", "congestion", "freetime extension", "surcharge")):
        return "freight", "heuristic_name"
    return "unmatched", "unclassified"


def quantity_rule(basis: str | None) -> str:
    text = (basis or "Container").strip().lower()
    if text in BILL_OF_LADING_BASES or any(token in text for token in BILL_OF_LADING_BASES):
        return "per_bill_of_lading"
    if "percent" in text:
        return "percent"
    return "per_container"


def convert_to_usd(amount: float | None, currency: str | None) -> float:
    if amount is None:
        return 0.0
    fx = FX_RATES.get((currency or "USD").upper(), 1.0)
    return round(amount * fx, 6)
