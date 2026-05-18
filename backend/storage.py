from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    extractor TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    exit_code INTEGER,
    files_downloaded INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_created_at ON downloads(created_at DESC);
"""


@dataclass
class Download:
    id: int
    url: str
    extractor: str | None
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    files_downloaded: int
    error: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row_to_download(row: aiosqlite.Row) -> Download:
    return Download(
        id=row["id"],
        url=row["url"],
        extractor=row["extractor"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        exit_code=row["exit_code"],
        files_downloaded=row["files_downloaded"],
        error=row["error"],
    )


class Storage:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    @classmethod
    async def open(cls, path: Path) -> Storage:
        db = await aiosqlite.connect(path)
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await db.commit()
        return cls(db)

    async def close(self) -> None:
        await self._db.close()

    async def insert_pending(self, url: str, extractor: str | None) -> Download:
        cursor = await self._db.execute(
            "INSERT INTO downloads(url, extractor, status, created_at) VALUES(?, ?, ?, ?)",
            (url, extractor, "pending", _now()),
        )
        await self._db.commit()
        new_id = cursor.lastrowid
        assert new_id is not None
        got = await self.get(new_id)
        assert got is not None
        return got

    async def get(self, id_: int) -> Download | None:
        async with self._db.execute("SELECT * FROM downloads WHERE id = ?", (id_,)) as cur:
            row = await cur.fetchone()
        return _row_to_download(row) if row else None

    async def list_recent(self, limit: int = 50) -> list[Download]:
        async with self._db.execute(
            "SELECT * FROM downloads ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_download(r) for r in rows]

    async def claim_next_pending(self) -> Download | None:
        async with self._db.execute(
            "SELECT id FROM downloads WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        await self._db.execute(
            "UPDATE downloads SET status = 'running', started_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        await self._db.commit()
        return await self.get(row["id"])

    async def finish_job(self, id_: int, exit_code: int, files_downloaded: int) -> None:
        status = "completed" if exit_code == 0 else "failed"
        await self._db.execute(
            "UPDATE downloads SET status = ?, finished_at = ?, exit_code = ?, "
            "files_downloaded = ? WHERE id = ?",
            (status, _now(), exit_code, files_downloaded, id_),
        )
        await self._db.commit()

    async def mark_failed(self, id_: int, error: str, files_downloaded: int) -> None:
        await self._db.execute(
            "UPDATE downloads SET status = 'failed', finished_at = ?, error = ?, "
            "files_downloaded = ? WHERE id = ?",
            (_now(), error, files_downloaded, id_),
        )
        await self._db.commit()
