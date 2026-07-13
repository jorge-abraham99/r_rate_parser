from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    raw_dir: Path
    registered_dir: Path
    templates_dir: Path
    runs_dir: Path
    warehouse_dir: Path

    @classmethod
    def load(cls, cwd: Path | None = None) -> "Settings":
        root_dir = Path(os.getenv("RATE_INGEST_ROOT", cwd or Path.cwd())).resolve()
        data_dir = root_dir / "data"
        return cls(
            root_dir=root_dir,
            data_dir=data_dir,
            raw_dir=data_dir / "sources" / "raw",
            registered_dir=data_dir / "sources" / "registered",
            templates_dir=data_dir / "templates",
            runs_dir=data_dir / "runs",
            warehouse_dir=data_dir / "warehouse",
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

