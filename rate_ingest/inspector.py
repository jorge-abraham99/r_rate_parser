from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from rate_ingest.models import InspectResult, SourceDocument


def inspect_source(source_document: SourceDocument) -> InspectResult:
    source_path = Path(source_document.source_path)
    source_type = source_document.source_type.lower()
    if source_type not in {"xlsx", "xlsm", "xls"}:
        return InspectResult(
            source_document=source_document,
            workbook_type=source_type,
            provider_guess=provider_from_name(source_document.file_name),
        )

    workbook = load_workbook(source_path, data_only=True, read_only=True)
    sheet_summaries = []
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        top_rows = []
        for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 10), values_only=True):
            values = [normalize_cell(value) for value in row]
            if any(values):
                top_rows.append(values[:12])
        sheet_summaries.append(
            {
                "sheet_name": sheet_name,
                "dimensions": f"{sheet.max_row} rows x {sheet.max_column} columns",
                "top_rows": top_rows,
            }
        )

    parser_guess = guess_parser_family(sheet_summaries)
    return InspectResult(
        source_document=source_document,
        workbook_type=source_type,
        provider_guess=provider_from_name(source_document.file_name),
        parser_family_guess=parser_guess,
        sheet_summaries=sheet_summaries,
    )


def provider_from_name(file_name: str) -> str | None:
    upper = file_name.upper()
    for provider in ("MSC", "COSCO", "MAERSK", "CMA"):
        if provider in upper:
            return provider
    return None


def guess_parser_family(sheet_summaries: list[dict[str, Any]]) -> str | None:
    flattened = " ".join(
        " ".join(" ".join(row) for row in summary.get("top_rows", [])) for summary in sheet_summaries
    ).upper()
    if "OFFER 1-1" in flattened or "SCHEDULED ROUTE" in flattened:
        return "offer_block"
    if "CUSTOMER" in flattened and "POL" in flattened and "POD" in flattened:
        return "tabular_lane"
    if "TERMS AND CONDITIONS - POL" in flattened or "VIA SOU" in flattened:
        return "matrix"
    return "unknown"


def normalize_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().replace("\n", " / ")

