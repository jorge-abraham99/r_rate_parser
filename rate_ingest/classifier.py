from __future__ import annotations

from rate_ingest.inspector import inspect_source
from rate_ingest.models import InspectResult, SourceDocument
from rate_ingest.template_matcher import find_best_template
from rate_ingest.config import Settings


def classify_source(settings: Settings, source_document: SourceDocument) -> tuple[InspectResult, list[dict]]:
    inspect_result = inspect_source(source_document)
    template, scored = find_best_template(settings, inspect_result)
    inspect_result.possible_templates = scored
    if template and inspect_result.parser_family_guess == "unknown":
        inspect_result.parser_family_guess = template.parser_family
    return inspect_result, scored

