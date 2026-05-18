from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def archive_db_path(self) -> Path:
        return self.data_dir / "archive.db"

    @property
    def jobs_db_path(self) -> Path:
        return self.data_dir / "jobs.db"


def load_settings() -> Settings:
    raw = os.environ.get("WEBUI_DATA_DIR")
    data_dir = Path(raw).resolve() if raw else DEFAULT_DATA_DIR.resolve()
    return Settings(data_dir=data_dir)
