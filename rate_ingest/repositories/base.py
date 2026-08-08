from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rate_ingest.models import (
    CanonicalRate,
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
    SourceDocument,
)


@dataclass(frozen=True)
class ApprovedRateLibrary:
    """Approved domain rows and their source metadata."""

    cards: tuple[RateCard, ...]
    offers: tuple[RateOffer, ...]
    charges: tuple[RateChargeLine, ...]
    notes: tuple[RateNote, ...]
    source_by_import: dict[str, dict[str, Any]]


class RateRepository(ABC):
    """Persistence operations used by the parser and Rate Desk services."""

    backend_name: str

    @abstractmethod
    def register_source_document(
        self,
        source_path: Path,
        *,
        uploaded_by: str | None = None,
    ) -> SourceDocument:
        raise NotImplementedError

    @abstractmethod
    def add_import(self, rate_import: RateImport) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_import(self, rate_import: RateImport) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_import_records(self) -> tuple[RateImport, ...]:
        raise NotImplementedError

    @abstractmethod
    def publish_import_bundle(
        self,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def remove_import_data(
        self,
        import_id: str,
        *,
        remove_import_record: bool = False,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_approved_rate_library(self) -> ApprovedRateLibrary:
        raise NotImplementedError
