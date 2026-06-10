from pathlib import Path

import aiosqlite
import pytest

from backend.database import open_database, transaction
from backend.downloads import service as downloads_service


async def test_migrate_adds_new_columns_to_legacy_db(tmp_path: Path) -> None:
    """Opening an old DB (without the postprocess columns) should add them."""
    db_path = tmp_path / "legacy.db"
    db = await aiosqlite.connect(db_path)
    # Older schema, minus the postprocess columns.
    await db.executescript(
        """
        CREATE TABLE downloads (
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
        INSERT INTO downloads(url, status, created_at) VALUES('u', 'completed', '2024-01-01');
        """
    )
    await db.commit()
    await db.close()

    conn = await open_database(db_path)
    try:
        d = await downloads_service.get(conn, 1)
        assert d is not None
        assert d.postprocess_status is None
        assert d.postprocess_chapters_packed is None
        assert d.postprocess_error is None
        assert d.files_expected is None
        assert d.chapters_total is None
    finally:
        await conn.close()


async def test_migrate_adds_verbose_trace_columns(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "jobs.db")
    try:
        async with db.execute("PRAGMA table_info(downloads)") as cur:
            dl_cols = {r["name"] for r in await cur.fetchall()}
        async with db.execute("PRAGMA table_info(download_files)") as cur:
            df_cols = {r["name"] for r in await cur.fetchall()}
    finally:
        await db.close()

    assert {"chapters_discovered", "chapters_failed"} <= dl_cols
    assert {"status", "pages", "title", "date", "error"} <= df_cols


async def test_migrate_is_idempotent_on_existing_db(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    db = await open_database(path)
    await db.close()
    # Re-open: _migrate runs again over a DB that already has the columns.
    db = await open_database(path)
    try:
        async with db.execute("PRAGMA table_info(download_files)") as cur:
            df_cols = {r["name"] for r in await cur.fetchall()}
    finally:
        await db.close()
    assert "status" in df_cols


async def test_manifest_cascades_on_download_delete(tmp_path: Path) -> None:
    """download_files has ON DELETE CASCADE; verify with a manual DELETE.

    The application never deletes downloads today, but the schema declares the
    constraint (and open_database turns FK enforcement on), so this guards
    against accidental removal of the cascade.
    """
    conn = await open_database(tmp_path / "jobs.db")
    try:
        d = await downloads_service.insert_pending(conn, "https://example/x", "fake")
        await downloads_service.save_manifest(conn, d.id, ["a.jpg"])
        await conn.execute("DELETE FROM downloads WHERE id = ?", (d.id,))
        await conn.commit()
        assert await downloads_service.get_manifest(conn, d.id) == []
    finally:
        await conn.close()


async def test_foreign_keys_enabled_by_open_database(tmp_path: Path) -> None:
    conn = await open_database(tmp_path / "jobs.db")
    try:
        async with conn.execute("PRAGMA foreign_keys") as cur:
            row = await cur.fetchone()
        assert row is not None and row[0] == 1
    finally:
        await conn.close()


async def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    conn = await open_database(tmp_path / "jobs.db")
    try:
        with pytest.raises(RuntimeError):
            async with transaction(conn):
                await conn.execute("INSERT INTO app_config(key, value) VALUES('doomed', '\"v\"')")
                raise RuntimeError("boom")
        # The partial write must not survive — neither immediately nor via a
        # later unrelated commit (the historical failure mode: the next
        # commit from any other task flushed orphaned statements).
        await conn.commit()
        async with conn.execute("SELECT 1 FROM app_config WHERE key = 'doomed'") as cur:
            assert await cur.fetchone() is None
    finally:
        await conn.close()


async def test_transaction_commits_on_success(tmp_path: Path) -> None:
    conn = await open_database(tmp_path / "jobs.db")
    try:
        async with transaction(conn):
            await conn.execute("INSERT INTO app_config(key, value) VALUES('k', '\"v\"')")
        async with conn.execute("SELECT value FROM app_config WHERE key = 'k'") as cur:
            assert await cur.fetchone() is not None
    finally:
        await conn.close()
