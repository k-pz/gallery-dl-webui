"""Database operations on the `targets` table."""

from __future__ import annotations

import json

import aiosqlite

from backend.database import insert_returning_id, now_iso, transaction
from backend.targets.schemas import Target


class Unset:
    """Sentinel allowing `update` to distinguish "leave as-is" from "set to NULL"."""


UNSET = Unset()


def _encode_tags(tags: list[str] | None) -> str | None:
    if tags is None:
        return None
    return json.dumps(list(tags), ensure_ascii=False)


# Bare target columns — no summary join. Used by `get`, `get_by_url`,
# `list_watched` and the upsert refetch.
_BARE_SELECT = "SELECT * FROM targets"

# Target columns plus the latest-download summary join (last_*, count).
# Used by `list_all` and `get_summary`; the result row Pydantic-validates
# back into Target with the summary fields populated.
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
    tags: list[str] | None = None,
    reading_direction: str | None = None,
) -> Target:
    """Find a target by URL, or create a fresh one. Updates output_dir/extractor
    from the latest submit so the next poll reuses what the user picked. When
    `tags` / `reading_direction` are supplied, they overwrite whatever the
    target currently has — last submit wins, so the user can re-submit to
    update series metadata.
    """
    async with db.execute(f"{_BARE_SELECT} WHERE url = ?", (url,)) as cur:
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
        if tags is not None:
            updates.append("tags = ?")
            params.append(_encode_tags(tags))
        if reading_direction is not None:
            updates.append("reading_direction = ?")
            params.append(reading_direction)
        if updates:
            params.append(row["id"])
            await db.execute(f"UPDATE targets SET {', '.join(updates)} WHERE id = ?", params)
            await db.commit()
            async with db.execute(f"{_BARE_SELECT} WHERE id = ?", (row["id"],)) as cur2:
                row = await cur2.fetchone()
        if row is None:
            raise RuntimeError("target row vanished mid-update")
        return Target.from_row(row)

    created_at = now_iso()
    new_id = await insert_returning_id(
        db,
        "INSERT INTO targets(url, extractor, output_dir, watched, created_at, "
        "tags, reading_direction) VALUES(?, ?, ?, ?, ?, ?, ?)",
        (
            url,
            extractor,
            output_dir,
            1 if watched else 0,
            created_at,
            _encode_tags(tags),
            reading_direction,
        ),
    )
    await db.commit()
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
        tags=list(tags) if tags is not None else [],
        reading_direction=reading_direction,
        series_status=None,
    )


async def get(db: aiosqlite.Connection, id_: int) -> Target | None:
    async with db.execute(f"{_BARE_SELECT} WHERE id = ?", (id_,)) as cur:
        row = await cur.fetchone()
    return Target.from_row(row) if row else None


async def get_by_url(db: aiosqlite.Connection, url: str) -> Target | None:
    async with db.execute(f"{_BARE_SELECT} WHERE url = ?", (url,)) as cur:
        row = await cur.fetchone()
    return Target.from_row(row) if row else None


async def list_all(db: aiosqlite.Connection) -> list[Target]:
    """List every target with the joined summary of its latest download."""
    async with db.execute(_SUMMARY_SELECT + " ORDER BY t.created_at DESC, t.id DESC") as cur:
        rows = await cur.fetchall()
    return [Target.from_row(r) for r in rows]


async def get_summary(db: aiosqlite.Connection, id_: int) -> Target | None:
    """Single-row equivalent of list_all — joined with the latest download."""
    async with db.execute(_SUMMARY_SELECT + " WHERE t.id = ?", (id_,)) as cur:
        row = await cur.fetchone()
    return Target.from_row(row) if row else None


async def update(
    db: aiosqlite.Connection,
    id_: int,
    *,
    watched: bool | None = None,
    watch_period: str | None | Unset = UNSET,
    output_dir: str | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    reading_direction: str | None | Unset = UNSET,
    series_status: str | None | Unset = UNSET,
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
    if not isinstance(tags, Unset):
        updates.append("tags = ?")
        params.append(_encode_tags(tags))
    if not isinstance(reading_direction, Unset):
        updates.append("reading_direction = ?")
        params.append(reading_direction)
    if not isinstance(series_status, Unset):
        updates.append("series_status = ?")
        params.append(series_status)
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


async def set_series_status(db: aiosqlite.Connection, id_: int, status: str) -> Target | None:
    """Persist a freshly auto-detected publication status (no-op when empty).

    Called by the download worker after the manifest simulation pass surfaces a
    normalised status from gallery-dl. We never overwrite an existing value
    here — the user's explicit PATCH always wins; auto-detect only fills the
    initial blank or refines a previously-blank target.
    """
    if not status:
        return await get(db, id_)
    await db.execute(
        "UPDATE targets SET series_status = ? WHERE id = ? "
        "AND (series_status IS NULL OR series_status = '')",
        (status, id_),
    )
    await db.commit()
    return await get(db, id_)


async def set_series_tags(db: aiosqlite.Connection, id_: int, tags: list[str]) -> Target | None:
    """Persist freshly auto-detected series tags/genres (no-op when empty).

    Fill-only: same shape as `set_series_status`. The user's explicit PATCH (or
    a re-submit that carries tags) always wins; auto-detect only populates
    targets whose tags column is NULL or an empty JSON array.
    """
    if not tags:
        return await get(db, id_)
    # `tags = '[]'` is the JSON sentinel for "user cleared all tags", but for
    # auto-fill purposes that and `NULL` mean the same thing — no value yet.
    await db.execute(
        "UPDATE targets SET tags = ? WHERE id = ? AND (tags IS NULL OR tags = '' OR tags = '[]')",
        (_encode_tags(tags), id_),
    )
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
    async with db.execute(f"{_BARE_SELECT} WHERE watched = 1 ORDER BY id ASC") as cur:
        rows = await cur.fetchall()
    return [Target.from_row(r) for r in rows]


# Series that are done publishing — a bulk refresh would never find new
# chapters for these, so they're excluded (same reasoning as unwatch_ended).
REFRESH_EXCLUDED_SERIES_STATUSES: tuple[str, ...] = ("Ended", "Abandoned")


async def list_watched_refreshable(db: aiosqlite.Connection) -> list[Target]:
    """Watched targets that may still get new chapters: series_status unset
    or anything outside REFRESH_EXCLUDED_SERIES_STATUSES."""
    placeholders = ",".join("?" * len(REFRESH_EXCLUDED_SERIES_STATUSES))
    async with db.execute(
        f"{_BARE_SELECT} WHERE watched = 1 "
        f"AND (series_status IS NULL OR series_status NOT IN ({placeholders})) "
        "ORDER BY id ASC",
        REFRESH_EXCLUDED_SERIES_STATUSES,
    ) as cur:
        rows = await cur.fetchall()
    return [Target.from_row(r) for r in rows]


async def unwatch_ended(db: aiosqlite.Connection) -> list[int]:
    """Flip `watched = 0` on every watched target whose series_status is "Ended".

    Returns the ids of the rows that were actually flipped, so callers can fan
    out events / log a per-target line without re-querying. Targets that are
    Ended but already unwatched aren't touched (and aren't reported), which
    keeps the count meaningful when re-running the job is a no-op.
    """
    async with db.execute(
        "SELECT id FROM targets WHERE watched = 1 AND series_status = 'Ended' ORDER BY id ASC"
    ) as cur:
        rows = await cur.fetchall()
    ids = [row["id"] for row in rows]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    await db.execute(
        f"UPDATE targets SET watched = 0 WHERE id IN ({placeholders})",
        ids,
    )
    await db.commit()
    return ids


async def delete(db: aiosqlite.Connection, id_: int) -> bool:
    # Download history outlives its target: detach referencing rows first so
    # the delete passes FK enforcement (downloads.target_id has no ON DELETE
    # action) and the rows keep their URL for the Recent list.
    async with transaction(db):
        await db.execute("UPDATE downloads SET target_id = NULL WHERE target_id = ?", (id_,))
        cursor = await db.execute("DELETE FROM targets WHERE id = ?", (id_,))
    return (cursor.rowcount or 0) > 0
