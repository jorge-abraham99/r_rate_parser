from __future__ import annotations

from rate_ingest.config import Settings
from rate_ingest.repositories.base import ApprovedRateLibrary, RateRepository
from rate_ingest.repositories.csv_repository import CsvRateRepository


def get_rate_repository(settings: Settings) -> RateRepository:
    if settings.rate_storage_backend == "csv":
        return CsvRateRepository(settings)
    if settings.rate_storage_backend == "postgres":
        raise RuntimeError(
            "RATE_STORAGE_BACKEND=postgres is reserved for Stage 4 and is not available yet."
        )
    raise ValueError(f"Unsupported rate storage backend: {settings.rate_storage_backend}")


__all__ = [
    "ApprovedRateLibrary",
    "CsvRateRepository",
    "RateRepository",
    "get_rate_repository",
]
