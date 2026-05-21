from pathlib import Path

import aiosqlite
import pytest

from backend.database import now_iso, open_database
from backend.maintenance import service


@pytest.fixture
async def db(tmp_path: Path):
    conn = await open_database(tmp_path / "jobs.db")
    try:
        yield conn
    finally:
        await conn.close()


async def _insert(db: aiosqlite.Connection, status: str, error: str | None = None) -> int:
    started = now_iso() if status != "pending" else None
    finished = now_iso() if status in {"completed", "failed", "cancelled"} else None
    cur = await db.execute(
        "INSERT INTO maintenance_jobs(kind, status, created_at, started_at, "
        "finished_at, error) VALUES ('rename_chapters', ?, ?, ?, ?, ?)",
        (status, now_iso(), started, finished, error),
    )
    await db.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


async def test_mark_interrupted_on_boot_only_affects_running(db: aiosqlite.Connection) -> None:
    running_id = await _insert(db, "running")
    pending_id = await _insert(db, "pending")
    completed_id = await _insert(db, "completed")
    failed_id = await _insert(db, "failed", error="earlier failure")
    cancelled_id = await _insert(db, "cancelled")

    n = await service.mark_interrupted_on_boot(db)
    assert n == 1

    run = await service.get_job(db, running_id)
    pend = await service.get_job(db, pending_id)
    done = await service.get_job(db, completed_id)
    fail = await service.get_job(db, failed_id)
    canc = await service.get_job(db, cancelled_id)

    assert run is not None and run.status == "failed"
    assert run.error == "interrupted: backend restarted"
    assert run.finished_at is not None
    assert pend is not None and pend.status == "pending"
    assert done is not None and done.status == "completed"
    assert fail is not None and fail.status == "failed" and fail.error == "earlier failure"
    assert canc is not None and canc.status == "cancelled"


async def test_mark_interrupted_on_boot_preserves_existing_error(
    db: aiosqlite.Connection,
) -> None:
    job_id = await _insert(db, "running", error="pre-existing")

    n = await service.mark_interrupted_on_boot(db)
    assert n == 1

    job = await service.get_job(db, job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.error == "pre-existing"
