"""SQLite connection lifecycle, schema, and migrations.

All persistent state lives in one aiosqlite database (`jobs.db`); each domain's
`service.py` runs its queries against the connection opened here. Schema and
migrations live in this one place so the DB shape has a single source of truth.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

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
    created_at TEXT NOT NULL,
    tags TEXT,
    reading_direction TEXT,
    series_status TEXT
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
    chapters_total INTEGER,
    chapters_discovered INTEGER,
    chapters_failed INTEGER,
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
    status TEXT,
    pages INTEGER,
    title TEXT,
    date TEXT,
    error TEXT,
    PRIMARY KEY (download_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_download_files_download_id
    ON download_files(download_id);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS maintenance_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    result_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_maintenance_jobs_status ON maintenance_jobs(status);
CREATE INDEX IF NOT EXISTS idx_maintenance_jobs_created_at ON maintenance_jobs(created_at DESC);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def insert_returning_id(db: aiosqlite.Connection, sql: str, params: Iterable[object]) -> int:
    """Run an INSERT and return its lastrowid, failing loud if it's missing.

    Centralises the cursor.lastrowid dance so callers never have to assert
    (asserts get stripped under `python -O`; the DB layer should fail loud).
    """
    cursor = await db.execute(sql, tuple(params))
    new_id = cursor.lastrowid
    if new_id is None:
        raise RuntimeError("INSERT returned no lastrowid")
    return new_id


async def open_database(path: Path) -> aiosqlite.Connection:
    """Open the SQLite file, install the schema, run migrations, and return it."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    await _migrate(db)
    await db.commit()
    return db


async def _migrate(db: aiosqlite.Connection) -> None:
    # Columns added after the initial schema; add any missing ones.
    async with db.execute("PRAGMA table_info(downloads)") as cur:
        cols = {row["name"] for row in await cur.fetchall()}
    if "files_expected" not in cols:
        await db.execute("ALTER TABLE downloads ADD COLUMN files_expected INTEGER")
    if "chapters_total" not in cols:
        await db.execute("ALTER TABLE downloads ADD COLUMN chapters_total INTEGER")
    if "chapters_discovered" not in cols:
        await db.execute("ALTER TABLE downloads ADD COLUMN chapters_discovered INTEGER")
    if "chapters_failed" not in cols:
        await db.execute("ALTER TABLE downloads ADD COLUMN chapters_failed INTEGER")
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
        await _backfill_targets(db)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_target_id ON downloads(target_id)")

    async with db.execute("PRAGMA table_info(download_files)") as cur:
        df_cols = {row["name"] for row in await cur.fetchall()}
    for col, decl in (
        ("status", "TEXT"),
        ("pages", "INTEGER"),
        ("title", "TEXT"),
        ("date", "TEXT"),
        ("error", "TEXT"),
    ):
        if col not in df_cols:
            await db.execute(f"ALTER TABLE download_files ADD COLUMN {col} {decl}")

    async with db.execute("PRAGMA table_info(targets)") as cur:
        target_cols = {row["name"] for row in await cur.fetchall()}
    if "name" not in target_cols:
        await db.execute("ALTER TABLE targets ADD COLUMN name TEXT")
    if "tags" not in target_cols:
        await db.execute("ALTER TABLE targets ADD COLUMN tags TEXT")
    if "reading_direction" not in target_cols:
        await db.execute("ALTER TABLE targets ADD COLUMN reading_direction TEXT")
    if "series_status" not in target_cols:
        await db.execute("ALTER TABLE targets ADD COLUMN series_status TEXT")


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
            (g["url"], g["extractor"], g["output_dir"], g["created_at"] or now_iso()),
        )
    await db.execute(
        "UPDATE downloads SET target_id = ("
        "  SELECT id FROM targets WHERE targets.url = downloads.url"
        ") WHERE target_id IS NULL"
    )
