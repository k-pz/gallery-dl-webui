"""Global application configuration loaded from the environment.

Per-domain knobs (delete-raw, default watch period, postprocess root) live in
the `app_config` table — see `backend.app_config` — and are mutable from the UI.
This module only covers the things uvicorn needs at startup: the data dir and
the host/port to bind.
"""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: tuple[str, ...] = ()
    cors_origin_regex: str | None = None

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def archive_db_path(self) -> Path:
        return self.data_dir / "archive.db"

    @property
    def jobs_db_path(self) -> Path:
        return self.data_dir / "jobs.db"


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(o.strip() for o in raw.split(",") if o.strip())


def load_settings() -> Settings:
    raw = os.environ.get("WEBUI_DATA_DIR")
    data_dir = Path(raw).resolve() if raw else DEFAULT_DATA_DIR.resolve()
    regex = os.environ.get("WEBUI_CORS_ORIGIN_REGEX")
    return Settings(
        data_dir=data_dir,
        host=os.environ.get("WEBUI_HOST", "0.0.0.0"),
        port=int(os.environ.get("WEBUI_PORT", "8000")),
        cors_origins=_parse_origins(os.environ.get("WEBUI_CORS_ORIGINS")),
        cors_origin_regex=regex if regex else None,
    )
