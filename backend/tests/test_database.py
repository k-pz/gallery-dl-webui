from pathlib import Path

import aiosqlite

from backend.database import open_database
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


async def test_manifest_cascades_on_download_delete(tmp_path: Path) -> None:
    """download_files has ON DELETE CASCADE; verify with a manual DELETE.

    The application never deletes downloads today, but the schema declares the
    constraint, so this guards against accidental removal of the cascade.
    """
    conn = await open_database(tmp_path / "jobs.db")
    try:
        d = await downloads_service.insert_pending(conn, "https://example/x", "fake")
        await downloads_service.save_manifest(conn, d.id, ["a.jpg"])
        # Enable FK enforcement (off by default in sqlite).
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("DELETE FROM downloads WHERE id = ?", (d.id,))
        await conn.commit()
        assert await downloads_service.get_manifest(conn, d.id) == []
    finally:
        await conn.close()
