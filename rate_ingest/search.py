from __future__ import annotations

from rich.console import Console
from rich.table import Table

from rate_ingest.config import Settings
from rate_ingest.repositories import RateRepository
from rate_ingest.services import search_approved_offers


def run_search(
    settings: Settings,
    *,
    repository: RateRepository | None = None,
    **filters,
) -> int:
    rows = search_approved_offers(
        settings,
        limit=5000,
        repository=repository,
        **filters,
    )
    console = Console()
    if not rows:
        console.print("No approved offers found.")
        return 0
    table = Table(title=f"Approved Offers ({len(rows)})")
    columns = []
    for column in [
        "provider_name",
        "carrier_name",
        "pol",
        "pod",
        "final_destination",
        "equipment_type",
        "base_amount",
        "base_currency",
        "source_file_name",
    ]:
        if any(column in row for row in rows):
            table.add_column(column)
            columns.append(column)
    for row in rows[:50]:
        table.add_row(*(str(row.get(column, "")) for column in columns))
    console.print(table)
    return len(rows)
