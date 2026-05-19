"""Filesystem queries for postprocess output dirs.

The picker only ever surfaces *direct children* of the configured root:
a series-level folder like `/mnt/nas/Media/Manga`, never a per-series
subdir. The packing step writes the series subdirectory itself.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from backend.app_config import service as app_config_service
from backend.exceptions import BadRequestError
from backend.output_dirs.schemas import DirEntry


class PostprocessRootNotConfigured(BadRequestError):
    detail = "postprocess_root is not configured"


async def resolve_root(db: aiosqlite.Connection) -> Path:
    cfg = await app_config_service.get_all(db)
    root_raw = cfg.get("postprocess_root")
    if not isinstance(root_raw, str) or not root_raw:
        raise PostprocessRootNotConfigured()
    return Path(root_raw)


def list_direct_children(root: Path) -> list[DirEntry]:
    """Return non-hidden first-level subdirectories of root."""
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    return [
        DirEntry(path=str(child), name=child.name, depth=1)
        for child in children
        if not child.name.startswith(".")
    ]
