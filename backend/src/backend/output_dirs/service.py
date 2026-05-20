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


async def resolve_excluded_dir_names(db: aiosqlite.Connection) -> set[str]:
    """Lower-cased set of directory names the picker should hide.

    Falls back to DEFAULT_EXCLUDED_DIR_NAMES until the user touches the config.
    """
    from backend.app_config.constants import DEFAULT_EXCLUDED_DIR_NAMES

    cfg = await app_config_service.get_all(db)
    raw = cfg.get("postprocess_excluded_dir_names")
    if isinstance(raw, list):
        return {name.lower() for name in raw if isinstance(name, str) and name}
    return {name.lower() for name in DEFAULT_EXCLUDED_DIR_NAMES}


def list_direct_children(root: Path, excluded: set[str] | None = None) -> list[DirEntry]:
    """Return non-hidden first-level subdirectories of root."""
    excluded_lower = excluded or set()
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    return [
        DirEntry(path=str(child), name=child.name, depth=1)
        for child in children
        if not child.name.startswith(".") and child.name.lower() not in excluded_lower
    ]
