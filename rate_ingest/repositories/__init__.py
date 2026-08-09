from __future__ import annotations

from threading import Lock

from rate_ingest.config import Settings
from rate_ingest.repositories.base import (
    LOCAL_CSV_ORGANIZATION_ID,
    ApprovedRateLibrary,
    OrganizationId,
    RateRepository,
)
from rate_ingest.repositories.csv_repository import CsvRateRepository
from rate_ingest.repositories.postgres_repository import PostgresRateRepository


_postgres_repositories: dict[Settings, PostgresRateRepository] = {}
_postgres_repositories_lock = Lock()


def get_rate_repository(settings: Settings) -> RateRepository:
    if settings.rate_storage_backend == "csv":
        return CsvRateRepository(settings)
    if settings.rate_storage_backend == "postgres":
        with _postgres_repositories_lock:
            repository = _postgres_repositories.get(settings)
            if repository is None:
                repository = PostgresRateRepository(settings)
                _postgres_repositories[settings] = repository
            return repository
    raise ValueError(f"Unsupported rate storage backend: {settings.rate_storage_backend}")


def close_rate_repositories() -> None:
    with _postgres_repositories_lock:
        repositories = tuple(_postgres_repositories.values())
        _postgres_repositories.clear()
    for repository in repositories:
        repository.close()


__all__ = [
    "ApprovedRateLibrary",
    "CsvRateRepository",
    "LOCAL_CSV_ORGANIZATION_ID",
    "OrganizationId",
    "PostgresRateRepository",
    "RateRepository",
    "close_rate_repositories",
    "get_rate_repository",
]
