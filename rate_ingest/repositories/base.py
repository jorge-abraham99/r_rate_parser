from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from rate_ingest.models import (
    CanonicalRate,
    RateCard,
    RateChargeLine,
    RateImport,
    RateNote,
    RateOffer,
    SourceDocument,
)


OrganizationId = UUID | str
LOCAL_CSV_ORGANIZATION_ID = "local-csv"


@dataclass(frozen=True)
class ApprovedRateLibrary:
    """Approved domain rows and their source metadata."""

    cards: tuple[RateCard, ...]
    offers: tuple[RateOffer, ...]
    charges: tuple[RateChargeLine, ...]
    notes: tuple[RateNote, ...]
    source_by_import: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ImportBundle:
    """One import's persisted source and structured parsed entities."""

    source: SourceDocument
    rate_import: RateImport
    cards: tuple[RateCard, ...]
    offers: tuple[RateOffer, ...]
    charges: tuple[RateChargeLine, ...]
    notes: tuple[RateNote, ...]


class RateRepository(ABC):
    """Persistence operations used by the parser and Rate Desk services."""

    backend_name: str

    @abstractmethod
    def register_source_document(
        self,
        source_path: Path,
        *,
        organization_id: OrganizationId,
        uploaded_by: str | None = None,
        original_file_name: str | None = None,
    ) -> SourceDocument:
        raise NotImplementedError

    def persist_source_file(
        self,
        source: SourceDocument,
        local_source_path: Path,
        *,
        organization_id: OrganizationId,
        access_token: str | None = None,
    ) -> SourceDocument:
        """Move an accepted source to durable storage when configured."""
        del local_source_path, organization_id, access_token
        return source

    @abstractmethod
    def add_import(
        self,
        rate_import: RateImport,
        *,
        organization_id: OrganizationId,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_import(
        self,
        rate_import: RateImport,
        *,
        organization_id: OrganizationId,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_import_record(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
    ) -> RateImport | None:
        raise NotImplementedError

    @abstractmethod
    def list_import_records(
        self,
        *,
        organization_id: OrganizationId,
    ) -> tuple[RateImport, ...]:
        raise NotImplementedError

    @abstractmethod
    def load_import_bundle(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
    ) -> ImportBundle | None:
        """Load one import's persisted source and parsed entities for review."""
        raise NotImplementedError

    @abstractmethod
    def publish_import_bundle(
        self,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
        *,
        organization_id: OrganizationId,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_import_bundle(
        self,
        rate_import: RateImport,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
        *,
        organization_id: OrganizationId,
    ) -> None:
        """Persist parsed rows before review. CSV keeps its legacy warehouse rule."""
        raise NotImplementedError

    @abstractmethod
    def approve_import(
        self,
        rate_import: RateImport,
        cards: list[RateCard],
        offers: list[RateOffer],
        charges: list[RateChargeLine],
        notes: list[RateNote],
        canonical_rates: list[CanonicalRate],
        *,
        organization_id: OrganizationId,
        carrier_key: str | None,
        approved_by: str,
        approved_by_user_id: str | None = None,
    ) -> RateImport:
        """Approve one import and archive its current carrier replacement."""
        raise NotImplementedError

    @abstractmethod
    def reject_import(
        self,
        rate_import: RateImport,
        reason: str,
        *,
        organization_id: OrganizationId,
        rejected_by_user_id: str | None = None,
    ) -> RateImport:
        """Reject an import without deleting its parsed rows."""
        raise NotImplementedError

    @abstractmethod
    def remove_import_data(
        self,
        import_id: str,
        *,
        organization_id: OrganizationId,
        remove_import_record: bool = False,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_approved_rate_library(
        self,
        *,
        organization_id: OrganizationId,
    ) -> ApprovedRateLibrary:
        raise NotImplementedError

    def persist_offer_locations(
        self,
        offers: list[RateOffer],
        *,
        organization_id: OrganizationId,
    ) -> None:
        """Persist canonical links for existing approved offers during backfill."""
        raise NotImplementedError(
            f"Location backfill is not implemented for {self.backend_name}"
        )
