"""Database operations on the `downloads` and `download_files` tables."""

from __future__ import annotations

import aiosqlite

from backend.database import insert_returning_id, now_iso
from backend.downloads.models import Download, row_to_download

# Bounds the race-loss retry inside `claim_next_pending`: each retry
# costs one extra SELECT, so a tight loop in test setups can need a few
# attempts. 8 has been more than enough in practice.
_CLAIM_RETRY_ATTEMPTS = 8


async def insert_pending(
    db: aiosqlite.Connection,
    url: str,
    extractor: str | None,
    output_dir: str | None = None,
    target_id: int | None = None,
) -> Download:
    created_at = now_iso()
    new_id = await insert_returning_id(
        db,
        "INSERT INTO downloads(url, extractor, status, created_at, output_dir, target_id) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (url, extractor, "pending", created_at, output_dir, target_id),
    )
    await db.commit()
    return Download(
        id=new_id,
        url=url,
        extractor=extractor,
        status="pending",
        created_at=created_at,
        started_at=None,
        finished_at=None,
        exit_code=None,
        files_downloaded=0,
        files_expected=None,
        chapters_total=None,
        error=None,
        postprocess_status=None,
        postprocess_chapters_packed=None,
        postprocess_error=None,
        output_dir=output_dir,
        target_id=target_id,
    )


async def get(db: aiosqlite.Connection, id_: int) -> Download | None:
    async with db.execute("SELECT * FROM downloads WHERE id = ?", (id_,)) as cur:
        row = await cur.fetchone()
    return row_to_download(row) if row else None


async def list_recent(db: aiosqlite.Connection, limit: int = 50) -> list[Download]:
    async with db.execute(
        "SELECT * FROM downloads ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [row_to_download(r) for r in rows]


async def claim_next_pending(db: aiosqlite.Connection) -> Download | None:
    """Pick the oldest pending row, flip it to `extracting`, return it.

    Two-step (SELECT then guarded UPDATE) so callers don't need RETURNING:
    the UPDATE includes `status = 'pending'` so a slot that lost the race
    sees `rowcount == 0` and retries — at worst we make one more SELECT.
    """
    for _ in range(_CLAIM_RETRY_ATTEMPTS):
        async with db.execute(
            "SELECT id FROM downloads WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        async with db.execute(
            "UPDATE downloads SET status = 'extracting', started_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (now_iso(), row["id"]),
        ) as cur:
            claimed = (cur.rowcount or 0) > 0
        await db.commit()
        if claimed:
            return await get(db, row["id"])
    return None


async def save_manifest(
    db: aiosqlite.Connection, download_id: int, chapter_names: list[str]
) -> None:
    """Persist the chapter list discovered by the metadata pull.

    Each chapter gets one row in `download_files`; we reuse that table even
    though the rows no longer represent individual files. `files_expected`
    and `chapters_total` both equal the chapter count — the legacy
    `files_*` columns are kept in sync so older UI fallbacks keep working.
    """
    await db.execute("DELETE FROM download_files WHERE download_id = ?", (download_id,))
    await db.executemany(
        "INSERT INTO download_files(download_id, idx, relpath) VALUES(?, ?, ?)",
        [(download_id, i, name) for i, name in enumerate(chapter_names)],
    )
    n = len(chapter_names)
    await db.execute(
        "UPDATE downloads SET files_expected = ?, chapters_total = ? WHERE id = ?",
        (n, n, download_id),
    )
    await db.commit()


async def get_manifest(db: aiosqlite.Connection, download_id: int) -> list[str]:
    """Return the chapter-name list previously saved by `save_manifest`."""
    async with db.execute(
        "SELECT relpath FROM download_files WHERE download_id = ? ORDER BY idx ASC",
        (download_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [r["relpath"] for r in rows]


async def mark_running(db: aiosqlite.Connection, id_: int) -> None:
    await db.execute("UPDATE downloads SET status = 'running' WHERE id = ?", (id_,))
    await db.commit()


async def finish_job(
    db: aiosqlite.Connection, id_: int, exit_code: int, files_downloaded: int
) -> None:
    status = "completed" if exit_code == 0 else "failed"
    await db.execute(
        "UPDATE downloads SET status = ?, finished_at = ?, exit_code = ?, "
        "files_downloaded = ? WHERE id = ?",
        (status, now_iso(), exit_code, files_downloaded, id_),
    )
    await db.commit()


async def mark_failed(
    db: aiosqlite.Connection, id_: int, error: str, files_downloaded: int
) -> None:
    await db.execute(
        "UPDATE downloads SET status = 'failed', finished_at = ?, error = ?, "
        "files_downloaded = ? WHERE id = ?",
        (now_iso(), error, files_downloaded, id_),
    )
    await db.commit()


async def cancel_pending(db: aiosqlite.Connection, id_: int) -> bool:
    """Atomically flip a still-pending row to cancelled. Returns True if changed."""
    cursor = await db.execute(
        "UPDATE downloads SET status = 'cancelled', finished_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (now_iso(), id_),
    )
    await db.commit()
    return (cursor.rowcount or 0) > 0


async def mark_cancelled(db: aiosqlite.Connection, id_: int, files_downloaded: int) -> None:
    await db.execute(
        "UPDATE downloads SET status = 'cancelled', finished_at = ?, "
        "files_downloaded = ? WHERE id = ?",
        (now_iso(), files_downloaded, id_),
    )
    await db.commit()


async def reset_to_pending(db: aiosqlite.Connection, id_: int) -> bool:
    """Reset a terminal row back to pending so the worker can re-pick it up.

    Also clears the cached manifest so the next run re-extracts (the gallery
    may have grown new chapters since the last attempt).
    """
    cursor = await db.execute(
        "UPDATE downloads SET status = 'pending', started_at = NULL, "
        "finished_at = NULL, exit_code = NULL, files_downloaded = 0, "
        "files_expected = NULL, chapters_total = NULL, error = NULL, "
        "postprocess_status = NULL, postprocess_chapters_packed = NULL, "
        "postprocess_error = NULL "
        "WHERE id = ? AND status IN ('completed', 'failed', 'cancelled')",
        (id_,),
    )
    if (cursor.rowcount or 0) == 0:
        await db.commit()
        return False
    await db.execute("DELETE FROM download_files WHERE download_id = ?", (id_,))
    await db.commit()
    return True


async def mark_interrupted_on_boot(db: aiosqlite.Connection) -> int:
    cursor = await db.execute(
        "UPDATE downloads SET status = 'failed', finished_at = ?, "
        "error = COALESCE(error, 'interrupted: backend restarted') "
        "WHERE status IN ('extracting', 'running')",
        (now_iso(),),
    )
    await db.commit()
    return cursor.rowcount or 0


async def mark_postprocess(
    db: aiosqlite.Connection,
    id_: int,
    status: str,
    chapters_packed: int | None = None,
    error: str | None = None,
) -> None:
    await db.execute(
        "UPDATE downloads SET postprocess_status = ?, "
        "postprocess_chapters_packed = ?, postprocess_error = ? WHERE id = ?",
        (status, chapters_packed, error, id_),
    )
    await db.commit()


async def delete_all(db: aiosqlite.Connection) -> int:
    """Drop every row from downloads + download_files. Returns the count deleted.

    Used by the rebuild_library maintenance job to fully reset download
    history; targets are preserved (they're the source of truth) and so is
    app_config (user-set knobs).
    """
    async with db.execute("SELECT COUNT(*) AS c FROM downloads") as cur:
        row = await cur.fetchone()
    count = int(row["c"]) if row else 0
    await db.execute("DELETE FROM download_files")
    await db.execute("DELETE FROM downloads")
    await db.commit()
    return count


async def has_active_for_target(db: aiosqlite.Connection, target_id: int) -> bool:
    async with db.execute(
        "SELECT 1 FROM downloads WHERE target_id = ? AND status IN "
        "('pending', 'extracting', 'running') LIMIT 1",
        (target_id,),
    ) as cur:
        row = await cur.fetchone()
    return row is not None
