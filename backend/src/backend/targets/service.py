"""Database operations on the `targets` table."""

from __future__ import annotations

import aiosqlite

from backend.database import now_iso
from backend.targets.models import (
    UNSET,
    Target,
    TargetSummary,
    Unset,
    row_to_target,
    row_to_target_summary,
)

_SUMMARY_SELECT = """
SELECT t.*,
       d.id AS last_download_id,
       d.status AS last_status,
       d.finished_at AS last_finished_at,
       d.created_at AS last_created_at,
       (SELECT COUNT(*) FROM downloads WHERE target_id = t.id) AS download_count
FROM targets t
LEFT JOIN downloads d ON d.id = (
    SELECT id FROM downloads
    WHERE target_id = t.id
    ORDER BY created_at DESC, id DESC LIMIT 1
)
"""


async def upsert(
    db: aiosqlite.Connection,
    url: str,
    extractor: str | None,
    output_dir: str | None,
    watched: bool = False,
) -> Target:
    """Find a target by URL, or create a fresh one. Updates output_dir/extractor
    from the latest submit so the next poll reuses what the user picked."""
    async with db.execute("SELECT * FROM targets WHERE url = ?", (url,)) as cur:
        row = await cur.fetchone()
    if row is not None:
        updates: list[str] = []
        params: list[object] = []
        if extractor and extractor != row["extractor"]:
            updates.append("extractor = ?")
            params.append(extractor)
        if output_dir is not None and output_dir != row["output_dir"]:
            updates.append("output_dir = ?")
            params.append(output_dir)
        if updates:
            params.append(row["id"])
            await db.execute(f"UPDATE targets SET {', '.join(updates)} WHERE id = ?", params)
            await db.commit()
            async with db.execute("SELECT * FROM targets WHERE id = ?", (row["id"],)) as cur2:
                row = await cur2.fetchone()
        assert row is not None
        return row_to_target(row)

    created_at = now_iso()
    cursor = await db.execute(
        "INSERT INTO targets(url, extractor, output_dir, watched, created_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (url, extractor, output_dir, 1 if watched else 0, created_at),
    )
    await db.commit()
    new_id = cursor.lastrowid
    assert new_id is not None
    return Target(
        id=new_id,
        url=url,
        name=None,
        extractor=extractor,
        output_dir=output_dir,
        watched=watched,
        watch_period=None,
        last_polled_at=None,
        created_at=created_at,
    )


async def get(db: aiosqlite.Connection, id_: int) -> Target | None:
    async with db.execute("SELECT * FROM targets WHERE id = ?", (id_,)) as cur:
        row = await cur.fetchone()
    return row_to_target(row) if row else None


async def get_by_url(db: aiosqlite.Connection, url: str) -> Target | None:
    async with db.execute("SELECT * FROM targets WHERE url = ?", (url,)) as cur:
        row = await cur.fetchone()
    return row_to_target(row) if row else None


async def list_all(db: aiosqlite.Connection) -> list[TargetSummary]:
    """List every target with a tiny summary of its latest download."""
    async with db.execute(_SUMMARY_SELECT + " ORDER BY t.created_at DESC, t.id DESC") as cur:
        rows = await cur.fetchall()
    return [row_to_target_summary(r) for r in rows]


async def get_summary(db: aiosqlite.Connection, id_: int) -> TargetSummary | None:
    """Single-row equivalent of list_all — for routes that return one summary."""
    async with db.execute(_SUMMARY_SELECT + " WHERE t.id = ?", (id_,)) as cur:
        row = await cur.fetchone()
    return row_to_target_summary(row) if row else None


async def update(
    db: aiosqlite.Connection,
    id_: int,
    *,
    watched: bool | None = None,
    watch_period: str | None | Unset = UNSET,
    output_dir: str | None | Unset = UNSET,
) -> Target | None:
    updates: list[str] = []
    params: list[object] = []
    if watched is not None:
        updates.append("watched = ?")
        params.append(1 if watched else 0)
    if not isinstance(watch_period, Unset):
        updates.append("watch_period = ?")
        params.append(watch_period)
    if not isinstance(output_dir, Unset):
        updates.append("output_dir = ?")
        params.append(output_dir)
    if not updates:
        return await get(db, id_)
    params.append(id_)
    await db.execute(f"UPDATE targets SET {', '.join(updates)} WHERE id = ?", params)
    await db.commit()
    return await get(db, id_)


async def set_name(db: aiosqlite.Connection, id_: int, name: str) -> Target | None:
    """Capture or refresh the human-readable series name (no-op when empty)."""
    cleaned = name.strip() if isinstance(name, str) else ""
    if not cleaned:
        return await get(db, id_)
    await db.execute("UPDATE targets SET name = ? WHERE id = ?", (cleaned, id_))
    await db.commit()
    return await get(db, id_)


async def list_names(db: aiosqlite.Connection, ids: list[int]) -> dict[int, str | None]:
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    async with db.execute(
        f"SELECT id, name FROM targets WHERE id IN ({placeholders})",
        ids,
    ) as cur:
        rows = await cur.fetchall()
    return {row["id"]: row["name"] for row in rows}


async def mark_polled(db: aiosqlite.Connection, id_: int) -> None:
    await db.execute("UPDATE targets SET last_polled_at = ? WHERE id = ?", (now_iso(), id_))
    await db.commit()


async def list_watched(db: aiosqlite.Connection) -> list[Target]:
    async with db.execute("SELECT * FROM targets WHERE watched = 1 ORDER BY id ASC") as cur:
        rows = await cur.fetchall()
    return [row_to_target(r) for r in rows]


async def delete(db: aiosqlite.Connection, id_: int) -> bool:
    cursor = await db.execute("DELETE FROM targets WHERE id = ?", (id_,))
    await db.commit()
    return (cursor.rowcount or 0) > 0
