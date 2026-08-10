from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _boolean_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _storage_backend_env() -> str:
    value = os.getenv("RATE_STORAGE_BACKEND", "csv").strip().lower()
    if value not in {"csv", "postgres"}:
        raise ValueError("RATE_STORAGE_BACKEND must be csv or postgres")
    return value


def _source_storage_backend_env() -> str:
    value = os.getenv("SOURCE_STORAGE_BACKEND", "filesystem").strip().lower()
    if value not in {"filesystem", "supabase"}:
        raise ValueError("SOURCE_STORAGE_BACKEND must be filesystem or supabase")
    return value


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    raw_dir: Path
    registered_dir: Path
    templates_dir: Path
    runs_dir: Path
    warehouse_dir: Path
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    supabase_db_url: str | None = None
    auth_required: bool = False
    rate_storage_backend: str = "csv"
    source_storage_backend: str = "filesystem"
    supabase_storage_bucket: str = "rate-sources"

    @classmethod
    def load(cls, cwd: Path | None = None) -> "Settings":
        root_dir = Path(os.getenv("RATE_INGEST_ROOT", cwd or Path.cwd())).resolve()
        data_dir = root_dir / "data"
        rate_storage_backend = _storage_backend_env()
        source_storage_backend = _source_storage_backend_env()
        if (
            source_storage_backend == "supabase"
            and rate_storage_backend != "postgres"
        ):
            raise ValueError(
                "SOURCE_STORAGE_BACKEND=supabase requires "
                "RATE_STORAGE_BACKEND=postgres"
            )
        return cls(
            root_dir=root_dir,
            data_dir=data_dir,
            raw_dir=data_dir / "sources" / "raw",
            registered_dir=data_dir / "sources" / "registered",
            templates_dir=data_dir / "templates",
            runs_dir=data_dir / "runs",
            warehouse_dir=data_dir / "warehouse",
            supabase_url=_optional_env("SUPABASE_URL"),
            supabase_publishable_key=_optional_env("SUPABASE_PUBLISHABLE_KEY"),
            supabase_db_url=_optional_env("SUPABASE_DB_URL"),
            auth_required=_boolean_env("AUTH_REQUIRED", default=True),
            rate_storage_backend=rate_storage_backend,
            source_storage_backend=source_storage_backend,
            supabase_storage_bucket=(
                _optional_env("SUPABASE_STORAGE_BUCKET") or "rate-sources"
            ),
        )

    def ensure(self) -> None:
        for path in (
            self.data_dir,
            self.raw_dir,
            self.registered_dir,
            self.templates_dir,
            self.runs_dir,
            self.warehouse_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.seed_missing_templates()

    def seed_missing_templates(self) -> None:
        """Install bundled templates that are absent from a persistent data volume.

        Existing files are deliberately left alone: templates in the data directory are
        operator-managed and may contain local adjustments.
        """
        bundled_templates_dir = Path(__file__).resolve().parent / "bundled_templates"
        if not bundled_templates_dir.exists():
            return
        for template_path in bundled_templates_dir.glob("*.yaml"):
            target_path = self.templates_dir / template_path.name
            if not target_path.exists():
                shutil.copyfile(template_path, target_path)
