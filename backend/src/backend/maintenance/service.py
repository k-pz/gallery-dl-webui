from __future__ import annotations

import json
from typing import Any

import aiosqlite

from backend.database import insert_returning_id, now_iso
from backend.maintenance.schemas import MaintenanceJob


async def create_pending(db: aiosqlite.Connection, kind: str) -> MaintenanceJob:
    created = now_iso()
    row_id = await insert_returning_id(
        db,
        "INSERT INTO maintenance_jobs(kind, status, created_at) VALUES (?, 'pending', ?)",
        (kind, created),
    )
    await db.commit()
    return MaintenanceJob(
        id=row_id,
        kind=kind,
        status="pending",
        created_at=created,
        started_at=None,
        finished_at=None,
        result=None,
        error=None,
    )


async def claim_next_pending(db: aiosqlite.Connection) -> MaintenanceJob | None:
    async with db.execute(
        "SELECT * FROM maintenance_jobs WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    started = now_iso()
    await db.execute(
        "UPDATE maintenance_jobs SET status = 'running', started_at = ? WHERE id = ?",
        (started, row["id"]),
    )
    await db.commit()
    async with db.execute("SELECT * FROM maintenance_jobs WHERE id = ?", (row["id"],)) as cur:
        updated = await cur.fetchone()
    if updated is None:
        return None
    return MaintenanceJob.from_row(updated)


async def mark_completed(db: aiosqlite.Connection, id_: int, result: dict[str, Any]) -> None:
    await db.execute(
        "UPDATE maintenance_jobs SET status = 'completed', "
        "finished_at = ?, result_json = ?, error = NULL WHERE id = ?",
        (now_iso(), json.dumps(result), id_),
    )
    await db.commit()


async def mark_failed(db: aiosqlite.Connection, id_: int, error: str) -> None:
    await db.execute(
        "UPDATE maintenance_jobs SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
        (now_iso(), error, id_),
    )
    await db.commit()


async def mark_cancelled(
    db: aiosqlite.Connection, id_: int, result: dict[str, Any] | None = None
) -> None:
    """Persist a 'cancelled' terminal status. Optionally stash partial progress."""
    await db.execute(
        "UPDATE maintenance_jobs SET status = 'cancelled', finished_at = ?, "
        "result_json = ?, error = NULL WHERE id = ?",
        (now_iso(), json.dumps(result) if result is not None else None, id_),
    )
    await db.commit()


async def cancel_pending(db: aiosqlite.Connection, id_: int) -> bool:
    """Atomically flip a still-pending row to cancelled. Returns True if changed."""
    cursor = await db.execute(
        "UPDATE maintenance_jobs SET status = 'cancelled', finished_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (now_iso(), id_),
    )
    await db.commit()
    return (cursor.rowcount or 0) > 0


async def mark_interrupted_on_boot(db: aiosqlite.Connection) -> int:
    cursor = await db.execute(
        "UPDATE maintenance_jobs SET status = 'failed', finished_at = ?, "
        "error = COALESCE(error, 'interrupted: backend restarted') "
        "WHERE status = 'running'",
        (now_iso(),),
    )
    await db.commit()
    return cursor.rowcount or 0


async def list_jobs(db: aiosqlite.Connection, limit: int = 50) -> list[MaintenanceJob]:
    async with db.execute(
        "SELECT * FROM maintenance_jobs ORDER BY id DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [MaintenanceJob.from_row(row) for row in rows]


async def get_job(db: aiosqlite.Connection, id_: int) -> MaintenanceJob | None:
    async with db.execute(
        "SELECT * FROM maintenance_jobs WHERE id = ?",
        (id_,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return MaintenanceJob.from_row(row)
