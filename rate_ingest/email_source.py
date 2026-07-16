from __future__ import annotations

from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from rate_ingest.normalize import normalize_text


def load_email_payload(path: Path) -> dict[str, Any]:
    message = BytesParser(policy=policy.default).parse(path.open("rb"))
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        try:
            content = part.get_content()
        except Exception:
            continue
        if content_type == "text/plain":
            plain_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(content)

    html_body = next((part for part in html_parts if normalize_text(part)), html_parts[0] if html_parts else "")
    received_at = None
    if message.get("date"):
        try:
            received_at = parsedate_to_datetime(message["date"])
        except (TypeError, ValueError, IndexError):
            received_at = None

    return {
        "subject": normalize_text(message.get("subject")),
        "sender": normalize_text(message.get("from")),
        "received_at": received_at,
        "plain_text": "\n".join(part for part in plain_parts if normalize_text(part)),
        "html_text": html_body,
        "tables": extract_html_tables(html_body),
    }


def extract_html_tables(html_text: str) -> list[pd.DataFrame]:
    if not normalize_text(html_text):
        return []
    try:
        return pd.read_html(StringIO(html_text))
    except ValueError:
        return []


def dataframe_preview(frame: pd.DataFrame, max_rows: int = 8, max_cols: int = 8) -> list[list[str]]:
    preview: list[list[str]] = []
    clipped = frame.iloc[:max_rows, :max_cols]
    for _, row in clipped.iterrows():
        values = [normalize_cell(value) for value in row.tolist()]
        if any(values):
            preview.append(values)
    return preview


def normalize_cell(value: object) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return normalize_text(value)


def provider_from_sender(sender: str) -> str | None:
    upper = sender.upper()
    if "CMA" in upper:
        return "CMA CGM"
    if "MSC" in upper:
        return "MSC"
    if "COSCO" in upper:
        return "COSCO"
    if "MAERSK" in upper:
        return "MAERSK"
    return None
