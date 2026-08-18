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
from rate_ingest.models import (
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
    ValidationReport,
    new_id,
)
from rate_ingest.parsers.email_table import parse_email as parse_email_table
from rate_ingest.parsers.cosco_pdf_quote import parse_pdf as parse_cosco_pdf_quote
from rate_ingest.parsers.hapag_door_matrix import (
    parse_workbook as parse_hapag_door_matrix_workbook,
)
from rate_ingest.parsers.hapag_india_rows import (
    parse_workbook as parse_hapag_india_rows_workbook,
)
from rate_ingest.parsers.haulage_matrix import (
    parse_workbook as parse_haulage_matrix_workbook,
)
from rate_ingest.parsers.matrix import parse_workbook as parse_matrix_workbook
from rate_ingest.parsers.msc_zoned_inline import extract_tier_rate_tables
from rate_ingest.parsers.msc_zoned_inline import (
    parse_workbook as parse_msc_zoned_inline_workbook,
)
from rate_ingest.parsers.offer_block import parse_workbook as parse_offer_block_workbook
from rate_ingest.parsers.site_to_site_rows import (
    parse_workbook as parse_site_to_site_workbook,
)
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
        "tier_rate_tables": read_json_if_exists(run_dir / "tier_rate_tables.json")
        or {},
        "review_markdown": read_review_markdown(run_dir),
        "approval": read_json_if_exists(run_dir / "approval.json"),
    }


def import_source_file(
    settings: Settings,
    source_path: Path,
    template: str | None = None,
    uploaded_by: str | None = None,
    source_file_name: str | None = None,
    source_storage_access_token: str | None = None,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    settings.ensure()
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    source = rate_repository.register_source_document(
        source_path,
        organization_id=repository_org_id,
        uploaded_by=uploaded_by,
        original_file_name=source_file_name or source_path.name,
    )
    parser_source = source.model_copy(update={"source_path": str(source_path)})
    inspected, _ = classify_source(settings, parser_source)
    scored = inspected.possible_templates
    if template:
        matched_template = next(
            (item for item in load_templates(settings) if item.template_id == template),
            None,
        )
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
            (
                item["confidence"]
                for item in scored
                if item["template_id"] == matched_template.template_id
            ),
            None,
        ),
        status="pending_review",
    )
    run_dir = settings.runs_dir / rate_import.id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "detected_structure.json", inspected.model_dump(mode="json"))

    card, offers, charges, notes = parse_source_by_family(
        source_path,
        matched_template.parser_family,
        matched_template,
        rate_import,
        source_file_name=source.file_name,
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
        write_json(
            run_dir / "tier_rate_tables.json",
            extract_tier_rate_tables(source_path, matched_template),
        )
    source = rate_repository.persist_source_file(
        source,
        source_path,
        organization_id=repository_org_id,
        access_token=source_storage_access_token,
    )
    write_json(run_dir / "source_snapshot.json", source.model_dump(mode="json"))
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    write_csv_rows(run_dir / "parsed_rate_cards.csv", [card.model_dump(mode="json")])
    write_csv_rows(
        run_dir / "parsed_rate_offers.csv",
        [offer.model_dump(mode="json") for offer in offers],
    )
    write_csv_rows(
        run_dir / "parsed_rate_charge_lines.csv",
        [charge.model_dump(mode="json") for charge in charges],
    )
    write_csv_rows(
        run_dir / "parsed_rate_notes.csv",
        [note.model_dump(mode="json") for note in notes],
    )
    write_json(
        run_dir / "canonical_rates.json",
        [rate.model_dump(mode="json") for rate in canonical_rates],
    )
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
    rate_repository.save_import_bundle(
        rate_import,
        [card],
        offers,
        charges,
        notes,
        canonical_rates,
        organization_id=repository_org_id,
    )

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


def get_import_detail(
    settings: Settings,
    import_id: str,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    bundle = rate_repository.load_import_bundle(
        import_id, organization_id=repository_org_id
    )
    if bundle is None:
        raise ValueError(f"Import not found: {import_id}")
    run_dir = settings.runs_dir / import_id
    payload = load_run_payload(run_dir) if run_dir.exists() else {}
    rate_import = bundle.rate_import
    cards = list(bundle.cards)
    offers = list(bundle.offers)
    charges = list(bundle.charges)
    notes = list(bundle.notes)
    card = cards[0] if cards else None
    canonical_rates = payload.get("canonical_rates")
    if canonical_rates is None:
        canonical_rates = (
            [rate.model_dump(mode="json") for rate in build_canonical_rates(card, offers)]
            if card
            else []
        )
    charge_bucket_summary = analyze_charge_collection(
        charges,
        base_currency=card.currency_default if card else None,
    )
    return {
        "import_id": import_id,
        "rate_import": rate_import.model_dump(mode="json"),
        "source": payload.get("source_snapshot") or bundle.source.model_dump(mode="json"),
        "detected_structure": payload.get("detected_structure") or {},
        "summary": {
            "rate_cards": len(cards),
            "rate_offers": len(offers),
            "charge_lines": len(charges),
            "notes": len(notes),
            "canonical_rates": len(canonical_rates),
        },
        "validation_report": payload.get("validation_report") or {
            "import_id": import_id,
            "summary": rate_import.validation_summary_json,
            "items": [],
        },
        "approval": payload.get("approval"),
        "review_markdown": payload.get("review_markdown"),
        "card": card.model_dump(mode="json") if card else None,
        "charge_bucket_summary": summarize_charge_analysis(charge_bucket_summary),
        "tier_rate_tables": payload.get("tier_rate_tables") or {},
        "offers_preview": [offer.model_dump(mode="json") for offer in offers[:50]],
        "charges_preview": [charge.model_dump(mode="json") for charge in charges[:50]],
        "notes_preview": [note.model_dump(mode="json") for note in notes[:30]],
        "canonical_rates": canonical_rates,
    }


def list_imports(
    settings: Settings,
    limit: int = 50,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> list[dict[str, Any]]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    imports: list[dict[str, Any]] = []
    for item in rate_repository.list_import_records(organization_id=repository_org_id):
        bundle = rate_repository.load_import_bundle(
            item.id, organization_id=repository_org_id
        )
        if bundle is None:
            continue
        run_dir = settings.runs_dir / item.id
        source_snapshot = read_json_if_exists(run_dir / "source_snapshot.json") or {}
        validation_report = read_json_if_exists(run_dir / "validation_report.json") or {
            "summary": item.validation_summary_json
        }
        source_snapshot = source_snapshot or bundle.source.model_dump(mode="json")
        card = bundle.cards[0] if bundle.cards else None
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
                "carrier_name": (
                    card.carrier_name or card.provider_name if card else None
                ),
                "carrier_key": source_snapshot.get("operator_carrier_key")
                or item.carrier_key,
                "carrier_label": source_snapshot.get("operator_carrier_label"),
                "contract_tag": source_snapshot.get("contract_tag"),
                "valid_from": serialize_date(card.valid_from) if card else None,
                "valid_to": serialize_date(card.valid_to) if card else None,
                "lane_count": len(bundle.offers),
                "validation_summary": validation_report.get(
                    "summary", item.validation_summary_json
                ),
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
    approved_by_user_id: str | None = None,
) -> dict[str, Any]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    run_dir = find_run_dir(settings, import_id)
    payload = load_run_payload(run_dir)
    rate_import = RateImport(**payload["rate_import"])
    validation_report = ValidationReport(**payload["validation_report"])
    cards = [RateCard(**deserialize_row(row)) for row in payload["rate_cards"]]
    offers = [RateOffer(**deserialize_row(row)) for row in payload["rate_offers"]]
    charges = [
        RateChargeLine(**deserialize_row(row)) for row in payload["rate_charge_lines"]
    ]
    notes = [RateNote(**deserialize_row(row)) for row in payload["rate_notes"]]
    if validation_report.summary.get("errors", 0) > 0:
        raise ValueError(
            "Import has blocking validation errors and cannot be approved."
        )
    if carrier_name and cards:
        cards[0].carrier_name = carrier_name
        cards[0].provider_name = carrier_name
    rate_import = approve_run(
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
        carrier_key=carrier_key,
        approved_by_user_id=approved_by_user_id,
    )
    if carrier_name and cards:
        write_csv_rows(
            run_dir / "parsed_rate_cards.csv",
            [card.model_dump(mode="json") for card in cards],
        )
    if carrier_key or carrier_label or contract_tag:
        source_snapshot = payload["source_snapshot"]
        source_snapshot["operator_carrier_key"] = carrier_key
        source_snapshot["operator_carrier_label"] = carrier_label or carrier_name
        source_snapshot["contract_tag"] = contract_tag
        write_json(run_dir / "source_snapshot.json", source_snapshot)
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    return get_import_detail(
        settings,
        import_id,
        repository=rate_repository,
        organization_id=repository_org_id,
    )


def reject_import_by_id(
    settings: Settings,
    import_id: str,
    reason: str,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
    rejected_by_user_id: str | None = None,
) -> dict[str, Any]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    run_dir = find_run_dir(settings, import_id)
    rate_import = RateImport(**read_json(run_dir / "rate_import.json"))
    rate_import = reject_run(
        settings,
        run_dir,
        rate_import,
        reason,
        repository=rate_repository,
        organization_id=repository_org_id,
        rejected_by_user_id=rejected_by_user_id,
    )
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    return get_import_detail(
        settings,
        import_id,
        repository=rate_repository,
        organization_id=repository_org_id,
    )


def delete_import_by_id(
    settings: Settings,
    import_id: str,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    run_dir = find_run_dir(settings, import_id)
    rate_repository.remove_import_data(
        import_id,
        organization_id=repository_org_id,
        remove_import_record=True,
    )
    shutil.rmtree(run_dir)
    return {"deleted": True, "import_id": import_id}


def search_approved_offers(
    settings: Settings,
    provider_name: str | None = None,
    carrier_name: str | None = None,
    collection: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    equipment_type: str | None = None,
    valid_on: str | None = None,
    material: str | None = None,
    offer_id: str | None = None,
    limit: int | None = 200,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
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
        if offer_id and offer.id != offer_id:
            continue
        if provider_name and not contains_text(card.provider_name, provider_name):
            continue
        if carrier_name and not contains_text(card.carrier_name, carrier_name):
            continue
        if collection and not contains_text(
            first_present(offer.place_of_receipt, offer.origin), collection
        ):
            continue
        if pol and not contains_text(offer.pol, pol):
            continue
        if pod and not contains_text(
            first_present(offer.pod, offer.final_destination), pod
        ):
            continue
        if (
            equipment_type
            and (offer.equipment_type or "").upper() != equipment_type.upper()
        ):
            continue
        if valid_on_date and not offer_valid_on(offer, card, valid_on_date):
            continue

        offer_charges = charges_by_offer.get(offer.id, [])
        note_bucket = notes_by_offer.get(offer.id) or notes_by_card.get(card.id, [])
        total_charge_codes = offer_total_charge_codes(offer)
        charge_analysis = analyze_charge_collection(
            offer_charges,
            base_currency=offer.base_currency or card.currency_default,
            base_amount=offer.base_amount,
            base_label=base_charge_label(offer),
            total_charge_codes=total_charge_codes,
            include_lines=include_details,
        )
        additive_charges = [
            charge
            for charge in offer_charges
            if not is_base_charge(charge)
            and charge_counts_toward_total(charge, total_charge_codes)
            and currencies_match(
                charge.currency, offer.base_currency or card.currency_default
            )
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
        if material and material.lower() not in {"all", "all materials"}:
            if not any(item.lower() == material.lower() for item in materials):
                continue
        result = {
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
            "origin_usd": group_subtotal(charge_analysis, "origin"),
            "freight_usd": group_subtotal(charge_analysis, "freight"),
            "destination_usd": group_subtotal(charge_analysis, "destination"),
            "unmatched_usd": charge_analysis["unmatched_subtotal_usd"],
            "charge_count": sum(
                group["line_count"] for group in charge_analysis["groups"]
            ) + charge_analysis["unmatched_charge_count"],
            "zero_charge_count": sum(
                group["zero_line_count"] for group in charge_analysis["groups"]
            ),
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
        }
        if include_details:
            result.update(
                {
                    "charge_analysis": charge_analysis,
                    "notes_summary": note_bucket[0].note_text
                    if note_bucket
                    else card.notes_summary,
                    "charges": [
                        charge.model_dump(mode="json") for charge in offer_charges
                    ],
                    "notes": [
                        note.model_dump(mode="json") for note in note_bucket[:10]
                    ],
                }
            )
        results.append(result)
    results.sort(
        key=lambda item: (
            item["all_in_usd"] is None,
            item["all_in_usd"] if item["all_in_usd"] is not None else float("inf"),
            item["carrier_name"] or "",
        )
    )
    return results if limit is None else results[:limit]


def search_rate_summaries(
    settings: Settings,
    *,
    provider_name: str | None = None,
    carrier_name: str | None = None,
    collection: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    equipment_type: str | None = None,
    material: str | None = None,
    valid_on: str | None = None,
    limit: int = 50,
    offset: int = 0,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    common = {
        "provider_name": provider_name,
        "carrier_name": carrier_name,
        "pol": pol,
        "pod": pod,
        "equipment_type": equipment_type,
        "material": material,
        "valid_on": valid_on,
        "limit": None,
        "repository": repository,
        "organization_id": organization_id,
        "include_details": False,
    }
    if collection:
        base_rates = [
            rate
            for rate in search_approved_offers(settings, **common)
            if not is_haulage_rate(rate) and not is_spot_rate_result(rate)
        ]
        collection_rates = [
            rate
            for rate in search_approved_offers(
                settings,
                collection=collection,
                **common,
            )
            if not is_haulage_rate(rate) and not is_spot_rate_result(rate)
        ]
        by_id = {
            rate["offer_id"]: rate
            for rate in base_rates
            if not is_door_rate_result(rate)
        }
        by_id.update({rate["offer_id"]: rate for rate in collection_rates})
        results = list(by_id.values())
        results.sort(key=summary_sort_key)
    else:
        results = [
            rate
            for rate in search_approved_offers(settings, **common)
            if not is_haulage_rate(rate) and not is_spot_rate_result(rate)
        ]

    total = len(results)
    page_limit = min(max(limit, 1), 50)
    page_offset = max(offset, 0)
    page = results[page_offset : page_offset + page_limit]
    return {
        "rates": [compact_rate_summary(rate) for rate in page],
        "pagination": {
            "limit": page_limit,
            "offset": page_offset,
            "total": total,
            "has_more": page_offset + page_limit < total,
        },
    }


def get_rate_offer_detail(
    settings: Settings,
    offer_id: str,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any] | None:
    matches = search_approved_offers(
        settings,
        offer_id=offer_id,
        limit=1,
        repository=repository,
        organization_id=organization_id,
    )
    return matches[0] if matches else None


def compact_rate_summary(rate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: rate.get(key)
        for key in (
            "offer_id",
            "rate_card_id",
            "provider_name",
            "carrier_name",
            "document_type",
            "commodity",
            "origin",
            "place_of_receipt",
            "pol",
            "pod",
            "final_destination",
            "equipment_type",
            "service_mode",
            "transit_time_days",
            "base_amount",
            "base_currency",
            "all_in_amount",
            "all_in_usd",
            "all_in_flag",
            "charge_total",
            "origin_usd",
            "freight_usd",
            "destination_usd",
            "unmatched_usd",
            "charge_count",
            "zero_charge_count",
            "valid_from",
            "valid_to",
            "raw_sheet_name",
            "source_file_name",
            "carrier_key",
            "carrier_label",
            "contract_tag",
            "materials",
            "offer_reference",
            "raw_row_reference",
            "routing_note",
        )
    }


def summary_sort_key(rate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        rate.get("all_in_usd") is None,
        rate.get("all_in_usd")
        if rate.get("all_in_usd") is not None
        else float("inf"),
        rate.get("carrier_name") or "",
    )


def is_door_rate_result(rate: dict[str, Any]) -> bool:
    text = " ".join(
        str(rate.get(key) or "")
        for key in ("contract_tag", "carrier_key", "carrier_label", "service_mode")
    ).lower()
    normalized_mode = (rate.get("service_mode") or "").strip().lower().replace("-", "/")
    return (
        "door" in text
        or normalized_mode in {"sd / cy", "sd/cy"}
        or normalized_mode.startswith("sd ")
    )


def is_spot_rate_result(rate: dict[str, Any]) -> bool:
    text = " ".join(
        str(rate.get(key) or "")
        for key in ("contract_tag", "carrier_label", "offer_reference", "source_file_name")
    ).lower()
    return "spot" in text


def get_rate_desk_data(
    settings: Settings,
    limit: int = 2000,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
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
    approved_at = [
        serialize_date(item.approved_at)
        for item in rate_repository.list_import_records(
            organization_id=repository_org_id
        )
        if item.approved_at
    ]
    last_refreshed = (
        max(approved_at, key=parse_datetime_sort_key) if approved_at else None
    )

    origin_map: dict[str, str] = {}
    dest_map: dict[str, str] = {}
    collection_map: dict[str, str] = {}
    for rate in quote_rates:
        val = first_present(rate.get("place_of_receipt"), rate.get("origin"))
        if val:
            collection_map.setdefault(normalize_location_key(val), val)
        val = first_present(
            rate.get("pol"), rate.get("place_of_receipt"), rate.get("origin")
        )
        if val:
            origin_map.setdefault(normalize_location_key(val), val)
        val = first_present(rate.get("final_destination"), rate.get("pod"))
        if val:
            dest_map.setdefault(normalize_location_key(val), val)
    origins = sorted(origin_map.values())
    destinations = sorted(dest_map.values())
    collections = sorted(collection_map.values())
    equipment_types = sorted(
        {rate["equipment_type"] for rate in quote_rates if rate.get("equipment_type")}
    )
    carriers = sorted(
        {
            first_present(rate.get("carrier_name"), rate.get("provider_name"))
            for rate in quote_rates
            if first_present(rate.get("carrier_name"), rate.get("provider_name"))
        }
    )
    materials = sorted(
        {material for rate in quote_rates for material in rate.get("materials", [])}
    )
    haulage_tariffs, door_pickups, haulage_currency = build_haulage_lookup(
        haulage_rates
    )
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


def get_rate_desk_metadata(
    settings: Settings,
    *,
    repository: RateRepository | None = None,
    organization_id: OrganizationId | None = None,
) -> dict[str, Any]:
    rate_repository = (
        repository if repository is not None else get_rate_repository(settings)
    )
    repository_org_id = resolve_repository_organization_id(settings, organization_id)
    library = rate_repository.load_approved_rate_library(
        organization_id=repository_org_id,
    )
    cards_by_id = {card.id: card for card in library.cards}
    quote_rates: list[dict[str, Any]] = []
    haulage_rates: list[dict[str, Any]] = []
    source_by_import = library.source_by_import
    for offer in library.offers:
        card = cards_by_id.get(offer.rate_card_id)
        if not card:
            continue
        source_payload = source_by_import.get(card.rate_import_id, {})
        rate = {
            "document_type": card.document_type,
            "provider_name": card.provider_name,
            "carrier_name": card.carrier_name,
            "place_of_receipt": offer.place_of_receipt,
            "origin": offer.origin,
            "pol": offer.pol,
            "pod": offer.pod,
            "final_destination": offer.final_destination,
            "equipment_type": offer.equipment_type,
            "base_amount": offer.base_amount,
            "base_currency": offer.base_currency or card.currency_default,
            "carrier_key": source_payload.get("operator_carrier_key"),
            "carrier_label": source_payload.get("operator_carrier_label"),
            "contract_tag": source_payload.get("contract_tag"),
            "source_file_name": source_payload.get("file_name"),
            "offer_reference": offer.offer_reference,
            "materials": infer_materials(
                offer.commodity or card.commodity,
                source_payload.get("operator_carrier_key"),
                source_payload.get("file_name"),
                offer.raw_sheet_name,
            ),
        }
        if is_spot_rate_result(rate):
            continue
        (haulage_rates if is_haulage_rate(rate) else quote_rates).append(rate)

    origin_map: dict[str, str] = {}
    destination_map: dict[str, str] = {}
    collection_map: dict[str, str] = {}
    for rate in quote_rates:
        value = rate.get("pol")
        if value:
            origin_map.setdefault(normalize_location_key(value), value)
        value = first_present(rate.get("final_destination"), rate.get("pod"))
        if value:
            destination_map.setdefault(normalize_location_key(value), value)
        value = first_present(rate.get("place_of_receipt"), rate.get("origin"))
        if value:
            collection_map.setdefault(normalize_location_key(value), value)

    tariffs, pickups, haulage_currency = build_haulage_lookup(haulage_rates)
    approved_at = [
        serialize_date(item.approved_at)
        for item in rate_repository.list_import_records(
            organization_id=repository_org_id
        )
        if item.approved_at
    ]
    last_refreshed = max(approved_at, key=parse_datetime_sort_key) if approved_at else None
    return {
        "last_refreshed": last_refreshed,
        "haulage_tariffs": tariffs,
        "haulage_currency": haulage_currency,
        "filters": {
            "origins": sorted(origin_map.values()),
            "destinations": sorted(destination_map.values()),
            "collection_places": sorted(collection_map.values()),
            "equipment_types": sorted(
                {rate["equipment_type"] for rate in quote_rates if rate.get("equipment_type")}
            ),
            "carriers": sorted(
                {
                    first_present(rate.get("carrier_name"), rate.get("provider_name"))
                    for rate in quote_rates
                    if first_present(rate.get("carrier_name"), rate.get("provider_name"))
                }
            ),
            "materials": sorted(
                {
                    material
                    for rate in quote_rates
                    for material in rate.get("materials", [])
                }
            ),
            "door_pickups": pickups,
        },
    }


def analyze_charge_collection(
    charges: list[RateChargeLine],
    *,
    base_currency: str | None = None,
    base_amount: float | None = None,
    base_label: str = "Basic Ocean Freight",
    total_charge_codes: set[str] | None = None,
    include_lines: bool = True,
) -> dict[str, Any]:
    grouped = {
        "origin": {
            "key": "origin",
            "label": "Origin charges",
            "lines": [],
            "line_count": 0,
            "zero_line_count": 0,
            "subtotal_usd": 0.0,
        },
        "freight": {
            "key": "freight",
            "label": "Freight charges",
            "lines": [],
            "line_count": 0,
            "zero_line_count": 0,
            "subtotal_usd": 0.0,
        },
        "destination": {
            "key": "destination",
            "label": "Destination charges",
            "lines": [],
            "line_count": 0,
            "zero_line_count": 0,
            "subtotal_usd": 0.0,
        },
        "unmatched": {
            "key": "unmatched",
            "label": "Unmatched charges",
            "lines": [],
            "line_count": 0,
            "zero_line_count": 0,
            "subtotal_usd": 0.0,
        },
    }
    matched_count = 0
    unmatched_count = 0

    has_base_line = any(is_base_charge(charge) for charge in charges)
    if charges:
        for charge in charges:
            bucket, matched_by = classify_charge_bucket(charge)
            usd_unit_amount = convert_to_usd(
                charge.amount, charge.currency or base_currency
            )
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
                "counts_toward_total": charge_counts_toward_total(charge, total_charge_codes),
            }
            grouped[bucket]["line_count"] += 1
            if line["zero_rated"]:
                grouped[bucket]["zero_line_count"] += 1
            if include_lines:
                grouped[bucket]["lines"].append(line)
            if line["counts_toward_total"]:
                grouped[bucket]["subtotal_usd"] += usd_unit_amount
            if bucket == "unmatched":
                unmatched_count += 1
            else:
                matched_count += 1
    if base_amount is not None and not has_base_line:
        usd_unit_amount = convert_to_usd(base_amount, base_currency)
        synthetic_line = {
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
            "counts_toward_total": True,
        }
        grouped["freight"]["line_count"] += 1
        if synthetic_line["zero_rated"]:
            grouped["freight"]["zero_line_count"] += 1
        if include_lines:
            grouped["freight"]["lines"].append(synthetic_line)
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
                "line_count": group["line_count"],
                "zero_line_count": group["zero_line_count"],
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
        **{
            key: value
            for key, value in analysis.items()
            if key not in {"groups", "unmatched_lines"}
        },
        "groups": [
            {key: value for key, value in group.items() if key != "lines"}
            for group in analysis.get("groups", [])
        ],
    }


def group_subtotal(analysis: dict[str, Any], key: str) -> float:
    return next(
        (
            float(group.get("subtotal_usd") or 0)
            for group in analysis.get("groups", [])
            if group.get("key") == key
        ),
        0.0,
    )


def offer_total_charge_codes(offer: RateOffer) -> set[str] | None:
    configured = offer.raw_row_json.get("total_charge_codes")
    if not isinstance(configured, list):
        return None
    return {normalize_charge_key(value) for value in configured if normalize_charge_key(value)}


def charge_counts_toward_total(
    charge: RateChargeLine,
    total_charge_codes: set[str] | None,
) -> bool:
    if total_charge_codes is None:
        return True
    candidates = {
        normalize_charge_key(charge.source_label),
        normalize_charge_key(charge.charge_name),
    }
    return bool(candidates & total_charge_codes)


def normalize_charge_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def parse_source_by_family(
    source_path: Path,
    parser_family: str,
    matched_template,
    rate_import: RateImport,
    *,
    source_file_name: str | None = None,
):
    if parser_family == "tabular_lane":
        return parse_tabular_workbook(source_path, matched_template, rate_import)
    if parser_family == "matrix":
        return parse_matrix_workbook(source_path, matched_template, rate_import)
    if parser_family == "haulage_matrix":
        return parse_haulage_matrix_workbook(source_path, matched_template, rate_import)
    if parser_family == "msc_zoned_inline":
        return parse_msc_zoned_inline_workbook(
            source_path, matched_template, rate_import
        )
    if parser_family == "hapag_door_matrix":
        return parse_hapag_door_matrix_workbook(
            source_path, matched_template, rate_import
        )
    if parser_family == "hapag_india_rows":
        return parse_hapag_india_rows_workbook(
            source_path, matched_template, rate_import
        )
    if parser_family == "cosco_pdf_quote":
        return parse_cosco_pdf_quote(source_path, matched_template, rate_import)
    if parser_family == "offer_block":
        return parse_offer_block_workbook(source_path, matched_template, rate_import)
    if parser_family == "site_to_site_rows":
        return parse_site_to_site_workbook(
            source_path,
            matched_template,
            rate_import,
            source_file_name=source_file_name,
        )
    if parser_family == "email_table":
        return parse_email_table(source_path, matched_template, rate_import)
    raise ValueError(
        f"Template {matched_template.template_id} uses unsupported parser family {parser_family}."
    )


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
    text = " ".join(
        filter(None, [commodity, carrier_key, source_file_name, sheet_name])
    ).lower()
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
    return (
        document_type == "inland_export"
        or carrier_key == "haulage-q2"
        or contract_tag == "HAUL"
    )


def normalize_location_key(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[,\s]+(?:gb|uk)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_haulage_lookup(
    haulage_rates: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]], str | None]:
    pickups: dict[str, dict[str, Any]] = {}
    tariffs: dict[str, dict[str, float]] = {}
    haulage_currency: str | None = None
    for rate in haulage_rates:
        collection = first_present(rate.get("place_of_receipt"), rate.get("origin"))
        port = first_present(
            rate.get("pol"), rate.get("final_destination"), rate.get("pod")
        )
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
        tariffs.setdefault(key, {})[normalize_location_key(port)] = round(
            float(amount), 2
        )
    return (
        tariffs,
        sorted(pickups.values(), key=lambda item: item["name"]),
        haulage_currency,
    )


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
    if any(
        token in name
        for token in (
            "origin",
            "export",
            "haulage",
            "intermodal",
            "pickup",
            "inland",
            "rail",
            "truck",
        )
    ):
        return "origin", "heuristic_name"
    if any(
        token in name
        for token in (
            "destination",
            "import",
            "terminal handling",
            "documentation",
            "documentation fee",
            "container protect",
            "delivery",
            "dthc",
        )
    ):
        return "destination", "heuristic_name"
    if any(
        token in name
        for token in (
            "bunker",
            "ocean freight",
            "emission",
            "peak season",
            "contingency",
            "congestion",
            "freetime extension",
            "surcharge",
        )
    ):
        return "freight", "heuristic_name"
    return "unmatched", "unclassified"


def quantity_rule(basis: str | None) -> str:
    text = (basis or "Container").strip().lower()
    if text in BILL_OF_LADING_BASES or any(
        token in text for token in BILL_OF_LADING_BASES
    ):
        return "per_bill_of_lading"
    if "percent" in text:
        return "percent"
    return "per_container"


def convert_to_usd(amount: float | None, currency: str | None) -> float:
    if amount is None:
        return 0.0
    fx = FX_RATES.get((currency or "USD").upper(), 1.0)
    return round(amount * fx, 6)
