from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rate_ingest.config import Settings
from rate_ingest.models import InspectResult, ParserTemplate


def load_templates(settings: Settings) -> list[ParserTemplate]:
    templates_by_id: dict[str, ParserTemplate] = {}
    bundled_dir = Path(__file__).resolve().parent / "bundled_templates"
    template_paths = [
        *sorted(bundled_dir.glob("*.yaml")),
        *sorted(settings.templates_dir.glob("*.yaml")),
    ]
    for path in template_paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload:
            parsed = ParserTemplate(**payload)
            templates_by_id[parsed.template_id] = parsed
    return [template for template in templates_by_id.values() if template.active]


def score_template(template: ParserTemplate, inspect_result: InspectResult) -> float:
    source_type = inspect_result.source_document.source_type.lower()
    template_type = template.file_type.lower()
    compatible_types = {template_type}
    if template_type == "xlsx":
        compatible_types.add("xlsm")
    if source_type not in compatible_types:
        return 0.0

    score = 0.0
    name_upper = inspect_result.source_document.file_name.upper()
    rules = template.match_rules

    filename_matches = [
        token for token in rules.get("filename_contains", [])
        if token.upper() in name_upper
    ]
    if rules.get("strong_filename_match") and filename_matches:
        score += 0.6
    else:
        score += 0.2 * len(filename_matches)

    sheet_names = [summary["sheet_name"].upper() for summary in inspect_result.sheet_summaries]
    required_sheet_tokens = rules.get("required_sheet_name_contains_all", [])
    if any(
        not any(token.upper() in sheet_name for sheet_name in sheet_names)
        for token in required_sheet_tokens
    ):
        return 0.0
    for token in rules.get("sheet_name_contains_any", []):
        if any(token.upper() in sheet_name for sheet_name in sheet_names):
            score += 0.15

    top_text = " ".join(
        " ".join(" ".join(row) for row in summary.get("top_rows", []))
        for summary in inspect_result.sheet_summaries
    ).upper()
    for header in rules.get("required_header_labels", []):
        if header.upper() in top_text:
            score += 0.15

    if inspect_result.provider_guess and template.provider_name:
        if inspect_result.provider_guess.upper() == template.provider_name.upper():
            score += 0.15

    if inspect_result.parser_family_guess == template.parser_family:
        score += 0.2

    return min(score, 0.99)


def find_best_template(settings: Settings, inspect_result: InspectResult) -> tuple[ParserTemplate | None, list[dict[str, Any]]]:
    scored = []
    for template in load_templates(settings):
        score = score_template(template, inspect_result)
        scored.append(
            {
                "template_id": template.template_id,
                "template_name": template.template_name,
                "confidence": round(score, 2),
                "parser_family_match": inspect_result.parser_family_guess == template.parser_family,
                "match_priority": int(template.match_rules.get("priority", 0)),
            }
        )
    scored.sort(
        key=lambda item: (
            item["confidence"],
            item["parser_family_match"],
            item["match_priority"],
        ),
        reverse=True,
    )
    best = scored[0] if scored else None
    if best and best["confidence"] >= 0.55:
        template = next(template for template in load_templates(settings) if template.template_id == best["template_id"])
        return template, scored
    return None, scored
