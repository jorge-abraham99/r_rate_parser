from __future__ import annotations

from rich.console import Console
from rich.table import Table

from rate_ingest.config import Settings
from rate_ingest.warehouse import search_offers


def run_search(settings: Settings, **filters) -> int:
    frame = search_offers(settings, **filters)
    console = Console()
    if frame.empty:
        console.print("No approved offers found.")
        return 0
    table = Table(title=f"Approved Offers ({len(frame)})")
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
        "file_name",
    ]:
        if column in frame.columns:
            table.add_column(column)
            columns.append(column)
    for _, row in frame.head(50).iterrows():
        table.add_row(*(str(row.get(column, "")) for column in columns))
    console.print(table)
    return len(frame)
