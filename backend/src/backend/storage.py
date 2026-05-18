import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

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
    files_expected INTEGER,
    error TEXT,
    postprocess_status TEXT,
    postprocess_chapters_packed INTEGER,
    postprocess_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_created_at ON downloads(created_at DESC);

CREATE TABLE IF NOT EXISTS download_files (
    download_id INTEGER NOT NULL REFERENCES downloads(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    relpath TEXT NOT NULL,
    PRIMARY KEY (download_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_download_files_download_id
    ON download_files(download_id);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
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
    files_expected: int | None
    error: str | None
    postprocess_status: str | None
    postprocess_chapters_packed: int | None
    postprocess_error: str | None


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
        files_expected=row["files_expected"],
        error=row["error"],
        postprocess_status=row["postprocess_status"],
        postprocess_chapters_packed=row["postprocess_chapters_packed"],
        postprocess_error=row["postprocess_error"],
    )


class Storage:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    @classmethod
    async def open(cls, path: Path) -> Self:
        db = await aiosqlite.connect(path)
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await cls._migrate(db)
        await db.commit()
        return cls(db)

    @staticmethod
    async def _migrate(db: aiosqlite.Connection) -> None:
        # Columns added after the initial schema; add any missing ones.
        async with db.execute("PRAGMA table_info(downloads)") as cur:
            cols = {row["name"] for row in await cur.fetchall()}
        if "files_expected" not in cols:
            await db.execute("ALTER TABLE downloads ADD COLUMN files_expected INTEGER")
        if "postprocess_status" not in cols:
            await db.execute("ALTER TABLE downloads ADD COLUMN postprocess_status TEXT")
        if "postprocess_chapters_packed" not in cols:
            await db.execute("ALTER TABLE downloads ADD COLUMN postprocess_chapters_packed INTEGER")
        if "postprocess_error" not in cols:
            await db.execute("ALTER TABLE downloads ADD COLUMN postprocess_error TEXT")

    async def close(self) -> None:
        await self._db.close()

    async def insert_pending(self, url: str, extractor: str | None) -> Download:
        created_at = _now()
        cursor = await self._db.execute(
            "INSERT INTO downloads(url, extractor, status, created_at) VALUES(?, ?, ?, ?)",
            (url, extractor, "pending", created_at),
        )
        await self._db.commit()
        new_id = cursor.lastrowid
        assert new_id is not None
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
            error=None,
            postprocess_status=None,
            postprocess_chapters_packed=None,
            postprocess_error=None,
        )

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
            "UPDATE downloads SET status = 'extracting', started_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        await self._db.commit()
        return await self.get(row["id"])

    async def save_manifest(self, download_id: int, relpaths: list[str]) -> None:
        await self._db.execute("DELETE FROM download_files WHERE download_id = ?", (download_id,))
        await self._db.executemany(
            "INSERT INTO download_files(download_id, idx, relpath) VALUES(?, ?, ?)",
            [(download_id, i, p) for i, p in enumerate(relpaths)],
        )
        await self._db.execute(
            "UPDATE downloads SET files_expected = ? WHERE id = ?",
            (len(relpaths), download_id),
        )
        await self._db.commit()

    async def get_manifest(self, download_id: int) -> list[str]:
        async with self._db.execute(
            "SELECT relpath FROM download_files WHERE download_id = ? ORDER BY idx ASC",
            (download_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [r["relpath"] for r in rows]

    async def mark_running(self, id_: int) -> None:
        await self._db.execute(
            "UPDATE downloads SET status = 'running' WHERE id = ?",
            (id_,),
        )
        await self._db.commit()

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

    async def mark_interrupted_on_boot(self) -> int:
        cursor = await self._db.execute(
            "UPDATE downloads SET status = 'failed', finished_at = ?, "
            "error = COALESCE(error, 'interrupted: backend restarted') "
            "WHERE status IN ('extracting', 'running')",
            (_now(),),
        )
        await self._db.commit()
        return cursor.rowcount or 0

    async def mark_postprocess(
        self,
        id_: int,
        status: str,
        chapters_packed: int | None = None,
        error: str | None = None,
    ) -> None:
        await self._db.execute(
            "UPDATE downloads SET postprocess_status = ?, "
            "postprocess_chapters_packed = ?, postprocess_error = ? WHERE id = ?",
            (status, chapters_packed, error, id_),
        )
        await self._db.commit()

    async def get_app_config(self) -> dict[str, Any]:
        async with self._db.execute("SELECT key, value FROM app_config") as cur:
            rows = await cur.fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    async def set_app_config(self, updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            await self._db.execute(
                "INSERT INTO app_config(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        await self._db.commit()
