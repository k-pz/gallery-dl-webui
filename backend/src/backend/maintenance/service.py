from __future__ import annotations

import json
from typing import Any

import aiosqlite

from backend.database import now_iso
from backend.maintenance.models import MaintenanceJob


def _row_to_job(row: aiosqlite.Row) -> MaintenanceJob:
    return MaintenanceJob(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        result_json=row["result_json"],
        error=row["error"],
    )


async def create_pending(db: aiosqlite.Connection, kind: str) -> MaintenanceJob:
    created = now_iso()
    cur = await db.execute(
        "INSERT INTO maintenance_jobs(kind, status, created_at) VALUES (?, 'pending', ?)",
        (kind, created),
    )
    await db.commit()
    row_id = cur.lastrowid
    if row_id is None:
        raise RuntimeError("failed to create maintenance job row")
    return MaintenanceJob(
        id=row_id,
        kind=kind,
        status="pending",
        created_at=created,
        started_at=None,
        finished_at=None,
        result_json=None,
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
    return _row_to_job(updated)


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


async def list_jobs(db: aiosqlite.Connection, limit: int = 50) -> list[MaintenanceJob]:
    async with db.execute(
        "SELECT * FROM maintenance_jobs ORDER BY id DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_job(row) for row in rows]


async def get_job(db: aiosqlite.Connection, id_: int) -> MaintenanceJob | None:
    async with db.execute(
        "SELECT * FROM maintenance_jobs WHERE id = ?",
        (id_,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_job(row)
