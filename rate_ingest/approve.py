from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rate_ingest.canonical import build_canonical_rates
from rate_ingest.config import Settings
from rate_ingest.models import RateImport, ValidationReport
from rate_ingest.repositories import OrganizationId, RateRepository
from rate_ingest.utils import write_json


def approve_import(
    settings: Settings,
    run_dir: Path,
    rate_import: RateImport,
    validation: ValidationReport,
    cards,
    offers,
    charges,
    notes,
    approved_by: str,
    *,
    repository: RateRepository,
    organization_id: OrganizationId,
    carrier_key: str | None = None,
    approved_by_user_id: str | None = None,
) -> RateImport:
    if validation.summary.get("errors", 0) > 0:
        raise ValueError(
            "Import has blocking validation errors and cannot be approved."
        )
    canonical_rates = build_canonical_rates(cards[0], offers) if cards else []
    approved = repository.approve_import(
        rate_import,
        cards,
        offers,
        charges,
        notes,
        canonical_rates,
        organization_id=organization_id,
        carrier_key=carrier_key,
        approved_by=approved_by,
        approved_by_user_id=approved_by_user_id,
    )
    approval_payload = {
        "import_id": approved.id,
        "decision": "approved",
        "approved_by": approved_by,
        "approved_at": (approved.approved_at or datetime.now(timezone.utc)).isoformat(),
    }
    write_json(run_dir / "approval.json", approval_payload)
    return approved


def reject_import(
    settings: Settings,
    run_dir: Path,
    rate_import: RateImport,
    reason: str,
    *,
    repository: RateRepository,
    organization_id: OrganizationId,
    rejected_by_user_id: str | None = None,
) -> RateImport:
    rejected = repository.reject_import(
        rate_import,
        reason,
        organization_id=organization_id,
        rejected_by_user_id=rejected_by_user_id,
    )
    approval_payload = {
        "import_id": rejected.id,
        "decision": "rejected",
        "reason": reason,
        "rejected_at": (rejected.rejected_at or datetime.now(timezone.utc)).isoformat(),
        "rejected_by": rejected_by_user_id,
    }
    write_json(run_dir / "approval.json", approval_payload)
    return rejected
