"""Database operations on the `app_config` table.

`app_config` is a flat key/value store of JSON-encoded values: each known key
maps to a typed value (string, bool, list[str]) that loaders/routers normalise
at the edges.
"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from backend.app_config.constants import KNOWN_OUTPUT_DIRS_LIMIT


async def get_all(db: aiosqlite.Connection) -> dict[str, Any]:
    async with db.execute("SELECT key, value FROM app_config") as cur:
        rows = await cur.fetchall()
    return {row["key"]: json.loads(row["value"]) for row in rows}


async def set_many(db: aiosqlite.Connection, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        await db.execute(
            "INSERT INTO app_config(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
    await db.commit()


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
