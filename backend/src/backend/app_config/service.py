"""Database operations on the `app_config` table.

`app_config` is a flat key/value store of JSON-encoded values: each known key
maps to a typed value (string, bool, list[str]) that loaders/routers normalise
at the edges.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from backend.app_config.constants import DEFAULT_EPUB_EXPORT_DIR_NAME, KNOWN_OUTPUT_DIRS_LIMIT
from backend.database import transaction


def coerce_clamped_int(value: Any, default: int, *, lo: int, hi: int) -> int:
    """Coerce a stored config value (int or numeric string) into [lo, hi].

    Anything unparseable — including bools, which are ints to Python but
    never a sane config value — falls back to `default`.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(lo, min(value, hi))
    if isinstance(value, str):
        try:
            return max(lo, min(int(value), hi))
        except ValueError:
            return default
    return default


def default_epub_export_dir(data_dir: Path) -> Path:
    return data_dir / DEFAULT_EPUB_EXPORT_DIR_NAME


def epub_export_dir(cfg: dict[str, Any], data_dir: Path) -> Path:
    """The effective EPUB export directory: the configured one, else the default."""
    raw = cfg.get("epub_export_dir")
    if isinstance(raw, str) and raw:
        return Path(raw)
    return default_epub_export_dir(data_dir)


async def get_all(db: aiosqlite.Connection) -> dict[str, Any]:
    async with db.execute("SELECT key, value FROM app_config") as cur:
        rows = await cur.fetchall()
    return {row["key"]: json.loads(row["value"]) for row in rows}


async def set_many(db: aiosqlite.Connection, updates: dict[str, Any]) -> None:
    async with transaction(db):
        await db.executemany(
            "INSERT INTO app_config(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(key, json.dumps(value)) for key, value in updates.items()],
        )


async def remember_output_dir(
    db: aiosqlite.Connection,
    output_dir: str,
    limit: int = KNOWN_OUTPUT_DIRS_LIMIT,
) -> list[str]:
    """Append `output_dir` to known_output_dirs (most-recent first, deduped)."""
    cfg = await get_all(db)
    known = cfg.get("postprocess_known_output_dirs") or []
    if not isinstance(known, list):
        known = []
    deduped = [output_dir] + [d for d in known if d != output_dir]
    deduped = deduped[:limit]
    await set_many(db, {"postprocess_known_output_dirs": deduped})
    return deduped
