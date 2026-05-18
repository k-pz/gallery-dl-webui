from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from gallery_dl import config, extractor, output
from gallery_dl.job import DownloadJob

from settings import Settings

_configured = False


def configure(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    output.initialize_logging(logging.INFO)
    config.set(("extractor",), "base-directory", str(settings.downloads_dir))
    config.set(("extractor",), "archive", str(settings.archive_db_path))
    _configured = True


def find_extractor(url: str) -> str | None:
    try:
        found = extractor.find(url)
    except Exception:
        return None
    if found is None:
        return None
    return getattr(found, "category", None)


def run_download(url: str, on_file: Callable[[], None]) -> int:
    job = DownloadJob(url)
    hooks: defaultdict[str, list[Callable[[Any], None]]] = defaultdict(list)
    hooks["file"].append(lambda _pathfmt: on_file())
    job.hooks = hooks
    return job.run()
