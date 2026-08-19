from __future__ import annotations

from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console

from rate_ingest.backfill import backfill_csv_to_postgres
from rate_ingest.config import Settings
from rate_ingest.inspector import inspect_source
from rate_ingest.search import run_search
from rate_ingest.services import (
    approve_import_by_id,
    backfill_location_catalogue,
    get_import_detail,
    import_source_file,
    reject_import_by_id,
)
from rate_ingest.repositories import LOCAL_CSV_ORGANIZATION_ID, get_rate_repository
from rate_ingest.template_matcher import find_best_template
from rate_ingest.utils import write_json

app = typer.Typer(help="Freight rate scripting-phase CLI.")
console = Console()


def settings() -> Settings:
    loaded = Settings.load()
    loaded.ensure()
    return loaded


@app.command(hidden=True, help="Inspect a source file without creating a full import. This is for debugging.")
def inspect(source_path: Path, uploaded_by: str | None = None) -> None:
    cfg = settings()
    source = get_rate_repository(cfg).register_source_document(
        source_path,
        organization_id=LOCAL_CSV_ORGANIZATION_ID,
        uploaded_by=uploaded_by,
    )
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
    try:
        result = import_source_file(cfg, source_path, template=template, uploaded_by=uploaded_by)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1)

    console.print(f"Import created: {result['import_id']}")
    console.print(f"Parser family: {result['parser_family']}")
    console.print(f"Template used: {result['template_id']}")
    console.print(f"Rate cards extracted: {result['counts']['rate_cards']}")
    console.print(f"Rate offers extracted: {result['counts']['rate_offers']}")
    console.print(f"Charge lines extracted: {result['counts']['charge_lines']}")
    console.print(f"Notes extracted: {result['counts']['notes']}")
    console.print(f"Validation warnings: {result['validation_summary'].get('warnings', 0)}")
    console.print(f"Review pack: {result['review_path']}")


@app.command(help="Print the generated review pack for an import.")
def review(import_id: str) -> None:
    cfg = settings()
    try:
        detail = get_import_detail(cfg, import_id)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1)
    if not detail.get("review_markdown"):
        console.print(f"No review pack found for {import_id}")
        raise typer.Exit(code=1)
    console.print(detail["review_markdown"])


@app.command(help="Approve an import and publish canonical rates to the local warehouse.")
def approve(import_id: str, approved_by: str = typer.Option(..., "--approved-by")) -> None:
    cfg = settings()
    try:
        approve_import_by_id(cfg, import_id, approved_by)
    except (ValueError, TypeError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1)
    console.print(f"Approved import {import_id} as {approved_by}")


@app.command(help="Reject an import and record the rejection reason.")
def reject(import_id: str, reason: str = typer.Option(..., "--reason")) -> None:
    cfg = settings()
    try:
        reject_import_by_id(cfg, import_id, reason)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1)
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


@app.command(
    "backfill-postgres",
    help="Check or copy all CSV import bundles into one Postgres organization for the production cutover.",
)
def backfill_postgres(
    organization_id: UUID,
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Perform the copy. Without this flag the command only validates the CSV data.",
    ),
) -> None:
    try:
        report = backfill_csv_to_postgres(
            Settings.load(), organization_id, apply=apply
        )
    except (RuntimeError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1)

    action = "Copied" if report.applied else "Validated"
    console.print(
        f"{action} {report.import_count} imports, {report.rate_card_count} cards, "
        f"{report.rate_offer_count} offers, {report.charge_line_count} charge lines, "
        f"and {report.note_count} notes."
    )


@app.command(
    "backfill-locations",
    help="Validate or apply canonical collection/destination links to approved imports.",
)
def backfill_locations(
    organization_id: str = typer.Option("", "--organization-id"),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Persist the links. Without this flag the command is a dry run.",
    ),
) -> None:
    cfg = settings()
    repository_org_id = organization_id or (
        LOCAL_CSV_ORGANIZATION_ID if cfg.rate_storage_backend == "csv" else None
    )
    if repository_org_id is None:
        console.print("--organization-id is required for Postgres storage")
        raise typer.Exit(code=1)
    try:
        report = backfill_location_catalogue(
            cfg,
            apply=apply,
            organization_id=repository_org_id,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1)
    action = "Updated" if report["applied"] else "Checked"
    console.print(
        f"{action} {report['offer_count']} approved offers: "
        f"{report['resolved_offer_count']} fully mapped, "
        f"{report['unresolved_count']} unresolved."
    )
    for issue in report["unresolved"][:50]:
        console.print(
            f"- {issue['role']}: {issue['raw_name'] or '(missing)'} "
            f"({issue['source_reference'] or issue['sheet_name'] or 'unknown row'})"
        )
