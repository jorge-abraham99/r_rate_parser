from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from rate_ingest.approve import approve_import as approve_run
from rate_ingest.approve import reject_import as reject_run
from rate_ingest.canonical import build_canonical_rates
from rate_ingest.classifier import classify_source
from rate_ingest.config import Settings
from rate_ingest.inspector import inspect_source
from rate_ingest.models import RateCard, RateChargeLine, RateImport, RateNote, RateOffer, ValidationReport, new_id
from rate_ingest.parsers.tabular_lane import parse_workbook
from rate_ingest.review import generate_review_markdown
from rate_ingest.search import run_search
from rate_ingest.source_registry import register_source
from rate_ingest.template_matcher import find_best_template
from rate_ingest.utils import read_csv_rows, read_json, write_csv_rows, write_json
from rate_ingest.validate import validate_import
from rate_ingest.warehouse import record_import

app = typer.Typer(help="Freight rate scripting-phase CLI.")
console = Console()


def settings() -> Settings:
    loaded = Settings.load()
    loaded.ensure()
    return loaded


def load_run_payload(run_dir: Path) -> dict:
    return {
        "rate_import": read_json(run_dir / "rate_import.json"),
        "rate_cards": read_csv_rows(run_dir / "parsed_rate_cards.csv"),
        "rate_offers": read_csv_rows(run_dir / "parsed_rate_offers.csv"),
        "rate_charge_lines": read_csv_rows(run_dir / "parsed_rate_charge_lines.csv"),
        "rate_notes": read_csv_rows(run_dir / "parsed_rate_notes.csv"),
        "validation_report": read_json(run_dir / "validation_report.json"),
    }


def find_run_dir(root: Path, import_id: str) -> Path:
    candidate = root / import_id
    if candidate.exists():
        return candidate
    raise typer.BadParameter(f"Run folder not found for import {import_id}")


@app.command(hidden=True, help="Inspect a source file without creating a full import. This is for debugging.")
def inspect(source_path: Path, uploaded_by: str | None = None) -> None:
    cfg = settings()
    source = register_source(cfg, source_path, uploaded_by=uploaded_by)
    inspected = inspect_source(source)
    _, scored = find_best_template(cfg, inspected)
    inspected.possible_templates = scored

    run_dir = cfg.runs_dir / f"inspect_{source.id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "source_snapshot.json", source.model_dump(mode="json"))
    write_json(run_dir / "detected_structure.json", inspected.model_dump(mode="json"))

    console.print(f"File: {source.file_name}")
    console.print(f"Type: {source.source_type}")
    console.print(f"Sheets found: {len(inspected.sheet_summaries)}")
    console.print(f"Likely parser family: {inspected.parser_family_guess}")
    console.print(f"Possible provider: {inspected.provider_guess or '-'}")
    if scored:
        console.print("Possible templates:")
        for item in scored[:5]:
            console.print(f"- {item['template_id']}, confidence {item['confidence']}")


@app.command("import", help="Run the normal ingestion step: detect a template, parse the file, validate it, and create a review pack.")
def import_source(source_path: Path, template: str | None = None, uploaded_by: str | None = None) -> None:
    cfg = settings()
    source = register_source(cfg, source_path, uploaded_by=uploaded_by)
    inspected, _ = classify_source(cfg, source)
    matched_template = None
    scored = inspected.possible_templates
    if template:
        from rate_ingest.template_matcher import load_templates

        matched_template = next((item for item in load_templates(cfg) if item.template_id == template), None)
    else:
        matched_template, scored = find_best_template(cfg, inspected)

    if not matched_template:
        console.print("No matching parser template found. Use inspect output to add a template.")
        raise typer.Exit(code=1)
    if matched_template.parser_family != "tabular_lane":
        console.print(
            f"Template {matched_template.template_id} uses parser family "
            f"{matched_template.parser_family}, which is not implemented yet in the scripting CLI."
        )
        raise typer.Exit(code=1)

    rate_import = RateImport(
        id=new_id("import"),
        source_document_id=source.id,
        parser_family=matched_template.parser_family,
        template_id=matched_template.template_id,
        classification_confidence=next((item["confidence"] for item in scored if item["template_id"] == matched_template.template_id), None),
        status="pending_review",
    )
    run_dir = cfg.runs_dir / rate_import.id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "source_snapshot.json", source.model_dump(mode="json"))
    write_json(run_dir / "detected_structure.json", inspected.model_dump(mode="json"))

    card, offers, charges, notes = parse_workbook(Path(source.source_path), matched_template, rate_import)
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

    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    write_csv_rows(run_dir / "parsed_rate_cards.csv", [card.model_dump(mode="json")])
    write_csv_rows(run_dir / "parsed_rate_offers.csv", [offer.model_dump(mode="json") for offer in offers])
    write_csv_rows(run_dir / "parsed_rate_charge_lines.csv", [charge.model_dump(mode="json") for charge in charges])
    write_csv_rows(run_dir / "parsed_rate_notes.csv", [note.model_dump(mode="json") for note in notes])
    write_json(
        run_dir / "canonical_rates.json",
        [rate.model_dump(mode="json") for rate in build_canonical_rates(card, offers)],
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
    record_import(cfg, rate_import)

    console.print(f"Import created: {rate_import.id}")
    console.print(f"Parser family: {rate_import.parser_family}")
    console.print(f"Template used: {matched_template.template_id}")
    console.print(f"Rate cards extracted: 1")
    console.print(f"Rate offers extracted: {len(offers)}")
    console.print(f"Charge lines extracted: {len(charges)}")
    console.print(f"Notes extracted: {len(notes)}")
    console.print(f"Validation warnings: {validation.summary.get('warnings', 0)}")
    console.print(f"Review pack: {review_path}")


@app.command(help="Print the generated review pack for an import.")
def review(import_id: str) -> None:
    cfg = settings()
    run_dir = find_run_dir(cfg.runs_dir, import_id)
    review_path = run_dir / "review.md"
    if not review_path.exists():
        console.print(f"No review pack found for {import_id}")
        raise typer.Exit(code=1)
    console.print(review_path.read_text(encoding="utf-8"))


@app.command(help="Approve an import and publish canonical rates to the local warehouse.")
def approve(import_id: str, approved_by: str = typer.Option(..., "--approved-by")) -> None:
    cfg = settings()
    run_dir = find_run_dir(cfg.runs_dir, import_id)
    payload = load_run_payload(run_dir)
    rate_import = RateImport(**payload["rate_import"])
    validation_report = ValidationReport(**payload["validation_report"])
    cards = [RateCard(**deserialize_row(row)) for row in payload["rate_cards"]]
    offers = [RateOffer(**deserialize_row(row)) for row in payload["rate_offers"]]
    charges = [RateChargeLine(**deserialize_row(row)) for row in payload["rate_charge_lines"]]
    notes = [RateNote(**deserialize_row(row)) for row in payload["rate_notes"]]
    approve_run(cfg, run_dir, rate_import, validation_report, cards, offers, charges, notes, approved_by)
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    console.print(f"Approved import {import_id} as {approved_by}")


@app.command(help="Reject an import and record the rejection reason.")
def reject(import_id: str, reason: str = typer.Option(..., "--reason")) -> None:
    cfg = settings()
    run_dir = find_run_dir(cfg.runs_dir, import_id)
    rate_import = RateImport(**read_json(run_dir / "rate_import.json"))
    reject_run(cfg, run_dir, rate_import, reason)
    write_json(run_dir / "rate_import.json", rate_import.model_dump(mode="json"))
    console.print(f"Rejected import {import_id}: {reason}")


@app.command(help="Search approved canonical rates that have already been published.")
def search(
    provider_name: str | None = None,
    carrier_name: str | None = None,
    pol: str | None = None,
    pod: str | None = None,
    equipment_type: str | None = None,
    valid_on: str | None = None,
) -> None:
    cfg = settings()
    run_search(
        cfg,
        provider_name=provider_name,
        carrier_name=carrier_name,
        pol=pol,
        pod=pod,
        equipment_type=equipment_type,
        valid_on=valid_on,
    )


def deserialize_row(row: dict[str, str]) -> dict[str, object]:
    parsed = {}
    for key, value in row.items():
        if value == "":
            parsed[key] = None
            continue
        if key in {"base_amount", "amount"}:
            parsed[key] = float(value)
            continue
        if key.endswith("_json"):
            try:
                parsed[key] = json.loads(value)
            except json.JSONDecodeError:
                parsed[key] = {} if key.endswith("_json") else value
            continue
        parsed[key] = value
    return parsed
