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
) -> None:
    if validation.summary.get("errors", 0) > 0:
        raise ValueError("Import has blocking validation errors and cannot be approved.")
    approval_payload = {
        "import_id": rate_import.id,
        "decision": "approved",
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_dir / "approval.json", approval_payload)
    rate_import.status = "approved"
    rate_import.approved_by = approved_by
    rate_import.approved_at = datetime.now(timezone.utc)
    canonical_rates = build_canonical_rates(cards[0], offers) if cards else []
    repository.publish_import_bundle(
        cards,
        offers,
        charges,
        notes,
        canonical_rates,
        organization_id=organization_id,
    )
    repository.update_import(rate_import, organization_id=organization_id)


def reject_import(
    settings: Settings,
    run_dir: Path,
    rate_import: RateImport,
    reason: str,
    *,
    repository: RateRepository,
    organization_id: OrganizationId,
) -> None:
    approval_payload = {
        "import_id": rate_import.id,
        "decision": "rejected",
        "reason": reason,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_dir / "approval.json", approval_payload)
    rate_import.status = "rejected"
    repository.update_import(rate_import, organization_id=organization_id)
