from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rate_ingest.config import Settings
from rate_ingest.models import InspectResult, ParserTemplate


def load_templates(settings: Settings) -> list[ParserTemplate]:
    templates: list[ParserTemplate] = []
    for path in sorted(settings.templates_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload:
            templates.append(ParserTemplate(**payload))
    return [template for template in templates if template.active]


def score_template(template: ParserTemplate, inspect_result: InspectResult) -> float:
    score = 0.0
    name_upper = inspect_result.source_document.file_name.upper()
    rules = template.match_rules

    for token in rules.get("filename_contains", []):
        if token.upper() in name_upper:
            score += 0.2

    sheet_names = [summary["sheet_name"].upper() for summary in inspect_result.sheet_summaries]
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
        scored.append({"template_id": template.template_id, "template_name": template.template_name, "confidence": round(score, 2)})
    scored.sort(key=lambda item: item["confidence"], reverse=True)
    best = scored[0] if scored else None
    if best and best["confidence"] >= 0.55:
        template = next(template for template in load_templates(settings) if template.template_id == best["template_id"])
        return template, scored
    return None, scored

