import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    name TEXT,
    extractor TEXT,
    output_dir TEXT,
    watched INTEGER NOT NULL DEFAULT 0,
    watch_period TEXT,
    last_polled_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_targets_watched ON targets(watched, last_polled_at);

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
    postprocess_error TEXT,
    output_dir TEXT,
    target_id INTEGER REFERENCES targets(id)
);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_created_at ON downloads(created_at DESC);
-- idx_downloads_target_id is created in _migrate after the column is ensured.

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
    output_dir: str | None
    target_id: int | None = None


@dataclass
class Target:
    id: int
    url: str
    name: str | None
    extractor: str | None
    output_dir: str | None
    watched: bool
    watch_period: str | None
    last_polled_at: str | None
    created_at: str


@dataclass
class TargetSummary:
    target: Target
    last_download_id: int | None
    last_status: str | None
    last_finished_at: str | None
    last_created_at: str | None
    download_count: int


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row_to_download(row: aiosqlite.Row) -> Download:
    target_id: int | None = None
    try:
        target_id = row["target_id"]
    except IndexError, KeyError:
        target_id = None
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
        output_dir=row["output_dir"],
        target_id=target_id,
    )


def _row_to_target(row: aiosqlite.Row) -> Target:
    return Target(
        id=row["id"],
        url=row["url"],
        name=row["name"],
        extractor=row["extractor"],
        output_dir=row["output_dir"],
        watched=bool(row["watched"]),
        watch_period=row["watch_period"],
        last_polled_at=row["last_polled_at"],
        created_at=row["created_at"],
    )


class _Unset:
    """Sentinel allowing update_target to distinguish "leave as-is" from "set to NULL"."""


_UNSET = _Unset()


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
        if "output_dir" not in cols:
            await db.execute("ALTER TABLE downloads ADD COLUMN output_dir TEXT")
        if "target_id" not in cols:
            await db.execute(
                "ALTER TABLE downloads ADD COLUMN target_id INTEGER REFERENCES targets(id)"
            )
            await Storage._backfill_targets(db)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_target_id ON downloads(target_id)"
        )

        async with db.execute("PRAGMA table_info(targets)") as cur:
            target_cols = {row["name"] for row in await cur.fetchall()}
        if "name" not in target_cols:
            await db.execute("ALTER TABLE targets ADD COLUMN name TEXT")

    @staticmethod
    async def _backfill_targets(db: aiosqlite.Connection) -> None:
        """For each distinct URL in existing downloads, create a target and link it."""
        async with db.execute(
            "SELECT url, MAX(extractor) AS extractor, MAX(output_dir) AS output_dir, "
            "MIN(created_at) AS created_at FROM downloads "
            "WHERE target_id IS NULL GROUP BY url"
        ) as cur:
            groups = await cur.fetchall()
        for g in groups:
            await db.execute(
                "INSERT OR IGNORE INTO targets(url, extractor, output_dir, created_at) "
                "VALUES (?, ?, ?, ?)",
                (g["url"], g["extractor"], g["output_dir"], g["created_at"] or _now()),
            )
        await db.execute(
            "UPDATE downloads SET target_id = ("
            "  SELECT id FROM targets WHERE targets.url = downloads.url"
            ") WHERE target_id IS NULL"
        )

    async def close(self) -> None:
        await self._db.close()

    async def insert_pending(
        self,
        url: str,
        extractor: str | None,
        output_dir: str | None = None,
        target_id: int | None = None,
    ) -> Download:
        created_at = _now()
        cursor = await self._db.execute(
            "INSERT INTO downloads(url, extractor, status, created_at, output_dir, target_id) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (url, extractor, "pending", created_at, output_dir, target_id),
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
            output_dir=output_dir,
            target_id=target_id,
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

    async def cancel_pending(self, id_: int) -> bool:
        """Atomically flip a still-pending row to cancelled. Returns True if changed."""
        cursor = await self._db.execute(
            "UPDATE downloads SET status = 'cancelled', finished_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_now(), id_),
        )
        await self._db.commit()
        return (cursor.rowcount or 0) > 0

    async def mark_cancelled(self, id_: int, files_downloaded: int) -> None:
        await self._db.execute(
            "UPDATE downloads SET status = 'cancelled', finished_at = ?, "
            "files_downloaded = ? WHERE id = ?",
            (_now(), files_downloaded, id_),
        )
        await self._db.commit()

    async def reset_to_pending(self, id_: int) -> bool:
        """Reset a terminal row back to pending so the worker can re-pick it up.

        Also clears the cached manifest so the next run re-extracts (the gallery
        may have grown new chapters since the last attempt).
        """
        cursor = await self._db.execute(
            "UPDATE downloads SET status = 'pending', started_at = NULL, "
            "finished_at = NULL, exit_code = NULL, files_downloaded = 0, "
            "files_expected = NULL, error = NULL, postprocess_status = NULL, "
            "postprocess_chapters_packed = NULL, postprocess_error = NULL "
            "WHERE id = ? AND status IN ('completed', 'failed', 'cancelled')",
            (id_,),
        )
        if (cursor.rowcount or 0) == 0:
            await self._db.commit()
            return False
        await self._db.execute("DELETE FROM download_files WHERE download_id = ?", (id_,))
        await self._db.commit()
        return True

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

    async def remember_output_dir(self, output_dir: str, limit: int = 20) -> list[str]:
        """Append `output_dir` to known_output_dirs (most-recent first, deduped)."""
        cfg = await self.get_app_config()
        known = cfg.get("postprocess_known_output_dirs") or []
        if not isinstance(known, list):
            known = []
        deduped = [output_dir] + [d for d in known if d != output_dir]
        deduped = deduped[:limit]
        await self.set_app_config({"postprocess_known_output_dirs": deduped})
        return deduped

    # ---- Targets ---------------------------------------------------------

    async def upsert_target(
        self, url: str, extractor: str | None, output_dir: str | None
    ) -> Target:
        """Find a target by URL, or create a fresh one. Updates output_dir/extractor
        from the latest submit so the next poll reuses what the user picked."""
        async with self._db.execute("SELECT * FROM targets WHERE url = ?", (url,)) as cur:
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
                await self._db.execute(
                    f"UPDATE targets SET {', '.join(updates)} WHERE id = ?", params
                )
                await self._db.commit()
                async with self._db.execute(
                    "SELECT * FROM targets WHERE id = ?", (row["id"],)
                ) as cur2:
                    row = await cur2.fetchone()
            assert row is not None
            return _row_to_target(row)

        created_at = _now()
        cursor = await self._db.execute(
            "INSERT INTO targets(url, extractor, output_dir, created_at) VALUES(?, ?, ?, ?)",
            (url, extractor, output_dir, created_at),
        )
        await self._db.commit()
        new_id = cursor.lastrowid
        assert new_id is not None
        return Target(
            id=new_id,
            url=url,
            name=None,
            extractor=extractor,
            output_dir=output_dir,
            watched=False,
            watch_period=None,
            last_polled_at=None,
            created_at=created_at,
        )

    async def get_target(self, id_: int) -> Target | None:
        async with self._db.execute("SELECT * FROM targets WHERE id = ?", (id_,)) as cur:
            row = await cur.fetchone()
        return _row_to_target(row) if row else None

    async def get_target_by_url(self, url: str) -> Target | None:
        async with self._db.execute("SELECT * FROM targets WHERE url = ?", (url,)) as cur:
            row = await cur.fetchone()
        return _row_to_target(row) if row else None

    async def list_targets(self) -> list[TargetSummary]:
        """List every target with a tiny summary of its latest download."""
        async with self._db.execute(
            """
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
            ORDER BY t.created_at DESC, t.id DESC
            """
        ) as cur:
            rows = await cur.fetchall()
        return [
            TargetSummary(
                target=_row_to_target(r),
                last_download_id=r["last_download_id"],
                last_status=r["last_status"],
                last_finished_at=r["last_finished_at"],
                last_created_at=r["last_created_at"],
                download_count=r["download_count"] or 0,
            )
            for r in rows
        ]

    async def update_target(
        self,
        id_: int,
        *,
        watched: bool | None = None,
        watch_period: str | None | _Unset = _UNSET,
        output_dir: str | None | _Unset = _UNSET,
    ) -> Target | None:
        updates: list[str] = []
        params: list[object] = []
        if watched is not None:
            updates.append("watched = ?")
            params.append(1 if watched else 0)
        if not isinstance(watch_period, _Unset):
            updates.append("watch_period = ?")
            params.append(watch_period)
        if not isinstance(output_dir, _Unset):
            updates.append("output_dir = ?")
            params.append(output_dir)
        if not updates:
            return await self.get_target(id_)
        params.append(id_)
        await self._db.execute(f"UPDATE targets SET {', '.join(updates)} WHERE id = ?", params)
        await self._db.commit()
        return await self.get_target(id_)

    async def set_target_name(self, id_: int, name: str) -> Target | None:
        """Capture or refresh the human-readable series name (no-op when empty)."""
        cleaned = name.strip() if isinstance(name, str) else ""
        if not cleaned:
            return await self.get_target(id_)
        await self._db.execute(
            "UPDATE targets SET name = ? WHERE id = ?",
            (cleaned, id_),
        )
        await self._db.commit()
        return await self.get_target(id_)

    async def list_target_names(self, ids: list[int]) -> dict[int, str | None]:
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        async with self._db.execute(
            f"SELECT id, name FROM targets WHERE id IN ({placeholders})",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        return {row["id"]: row["name"] for row in rows}

    async def mark_target_polled(self, id_: int) -> None:
        await self._db.execute(
            "UPDATE targets SET last_polled_at = ? WHERE id = ?",
            (_now(), id_),
        )
        await self._db.commit()

    async def list_watched_targets(self) -> list[Target]:
        async with self._db.execute(
            "SELECT * FROM targets WHERE watched = 1 ORDER BY id ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_target(r) for r in rows]

    async def has_active_download_for_target(self, target_id: int) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM downloads WHERE target_id = ? AND status IN "
            "('pending', 'extracting', 'running') LIMIT 1",
            (target_id,),
        ) as cur:
            row = await cur.fetchone()
        return row is not None

    async def delete_target(self, id_: int) -> bool:
        cursor = await self._db.execute("DELETE FROM targets WHERE id = ?", (id_,))
        await self._db.commit()
        return (cursor.rowcount or 0) > 0
