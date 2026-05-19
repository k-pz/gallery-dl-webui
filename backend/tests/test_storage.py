from pathlib import Path

import pytest

from backend.storage import Storage


@pytest.fixture
async def storage(tmp_path: Path):
    s = await Storage.open(tmp_path / "jobs.db")
    try:
        yield s
    finally:
        await s.close()


async def test_insert_pending_starts_in_pending_state(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")

    assert d.id > 0
    assert d.url == "https://example/x"
    assert d.extractor == "fake"
    assert d.status == "pending"
    assert d.started_at is None
    assert d.finished_at is None
    assert d.files_downloaded == 0
    assert d.files_expected is None


async def test_get_returns_persisted_row(storage: Storage) -> None:
    inserted = await storage.insert_pending("https://example/x", None)
    fetched = await storage.get(inserted.id)

    assert fetched is not None
    assert fetched.id == inserted.id
    assert fetched.extractor is None


async def test_get_missing_returns_none(storage: Storage) -> None:
    assert await storage.get(9999) is None


async def test_list_recent_orders_newest_first(storage: Storage) -> None:
    a = await storage.insert_pending("https://example/a", "fake")
    b = await storage.insert_pending("https://example/b", "fake")
    c = await storage.insert_pending("https://example/c", "fake")

    rows = await storage.list_recent(10)
    ids = [r.id for r in rows]

    assert ids == [c.id, b.id, a.id]


async def test_list_recent_respects_limit(storage: Storage) -> None:
    for i in range(5):
        await storage.insert_pending(f"https://example/{i}", "fake")
    rows = await storage.list_recent(2)
    assert len(rows) == 2


async def test_claim_next_pending_advances_status(storage: Storage) -> None:
    first = await storage.insert_pending("https://example/a", "fake")
    second = await storage.insert_pending("https://example/b", "fake")

    claimed = await storage.claim_next_pending()
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == "extracting"
    assert claimed.started_at is not None

    # The next claim picks the next pending row.
    claimed2 = await storage.claim_next_pending()
    assert claimed2 is not None
    assert claimed2.id == second.id


async def test_claim_next_pending_returns_none_when_empty(storage: Storage) -> None:
    assert await storage.claim_next_pending() is None


async def test_save_and_get_manifest(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.save_manifest(d.id, ["ch1/001.jpg", "ch1/002.jpg"])

    manifest = await storage.get_manifest(d.id)
    fetched = await storage.get(d.id)

    assert manifest == ["ch1/001.jpg", "ch1/002.jpg"]
    assert fetched is not None
    assert fetched.files_expected == 2


async def test_save_manifest_replaces_existing(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.save_manifest(d.id, ["a.jpg", "b.jpg"])
    await storage.save_manifest(d.id, ["c.jpg"])

    assert await storage.get_manifest(d.id) == ["c.jpg"]
    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.files_expected == 1


async def test_mark_running(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.claim_next_pending()
    await storage.mark_running(d.id)

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "running"


async def test_finish_job_zero_exit_marks_completed(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.finish_job(d.id, exit_code=0, files_downloaded=4)

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "completed"
    assert fetched.exit_code == 0
    assert fetched.files_downloaded == 4
    assert fetched.finished_at is not None


async def test_finish_job_nonzero_exit_marks_failed(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.finish_job(d.id, exit_code=1, files_downloaded=2)

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.exit_code == 1


async def test_mark_failed_records_error(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.mark_failed(d.id, "boom", files_downloaded=0)

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.error == "boom"


async def test_mark_interrupted_on_boot_only_affects_in_flight(
    storage: Storage,
) -> None:
    # Insert one row and claim it so it ends up in "extracting".
    extracting_row = await storage.insert_pending("https://example/x1", "fake")
    claimed = await storage.claim_next_pending()
    assert claimed is not None and claimed.id == extracting_row.id

    # Another row that stays pending. claim_next_pending was already called, so
    # this one is left alone.
    pending_row = await storage.insert_pending("https://example/x2", "fake")

    # Running row.
    running_row = await storage.insert_pending("https://example/x3", "fake")
    await storage.mark_running(running_row.id)

    # Completed row.
    completed_row = await storage.insert_pending("https://example/x4", "fake")
    await storage.finish_job(completed_row.id, exit_code=0, files_downloaded=0)

    n = await storage.mark_interrupted_on_boot()
    assert n == 2

    extr = await storage.get(extracting_row.id)
    pend = await storage.get(pending_row.id)
    run = await storage.get(running_row.id)
    done = await storage.get(completed_row.id)

    assert extr is not None and extr.status == "failed" and extr.error is not None
    assert run is not None and run.status == "failed" and run.error is not None
    assert pend is not None and pend.status == "pending"
    assert done is not None and done.status == "completed"


async def test_app_config_round_trip(storage: Storage) -> None:
    assert await storage.get_app_config() == {}

    await storage.set_app_config({"postprocess_root": "/tmp/media", "delete_raw_after_pack": True})
    cfg = await storage.get_app_config()
    assert cfg == {"postprocess_root": "/tmp/media", "delete_raw_after_pack": True}

    await storage.set_app_config({"postprocess_root": None})
    cfg = await storage.get_app_config()
    assert cfg == {"postprocess_root": None, "delete_raw_after_pack": True}


async def test_remember_output_dir_dedupes_and_orders(storage: Storage) -> None:
    after = await storage.remember_output_dir("/m/a")
    assert after == ["/m/a"]
    after = await storage.remember_output_dir("/m/b")
    assert after == ["/m/b", "/m/a"]
    after = await storage.remember_output_dir("/m/a")
    assert after == ["/m/a", "/m/b"]


async def test_mark_postprocess_persists_state(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.mark_postprocess(d.id, "completed", chapters_packed=3, error=None)

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.postprocess_status == "completed"
    assert fetched.postprocess_chapters_packed == 3
    assert fetched.postprocess_error is None


async def test_migrate_adds_new_columns_to_legacy_db(tmp_path: Path) -> None:
    """Opening an old DB (without the postprocess columns) should add them."""
    import aiosqlite

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

    s = await Storage.open(db_path)
    try:
        d = await s.get(1)
        assert d is not None
        assert d.postprocess_status is None
        assert d.postprocess_chapters_packed is None
        assert d.postprocess_error is None
        assert d.files_expected is None
    finally:
        await s.close()


async def test_cancel_pending_flips_status_atomically(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    assert await storage.cancel_pending(d.id) is True

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "cancelled"
    assert fetched.finished_at is not None

    # Second call is a no-op (no longer pending).
    assert await storage.cancel_pending(d.id) is False


async def test_cancel_pending_skips_already_running_rows(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.claim_next_pending()  # → extracting

    assert await storage.cancel_pending(d.id) is False
    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "extracting"


async def test_mark_cancelled_records_finished_at_and_files(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.claim_next_pending()
    await storage.mark_cancelled(d.id, files_downloaded=3)

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "cancelled"
    assert fetched.files_downloaded == 3
    assert fetched.finished_at is not None


async def test_reset_to_pending_clears_terminal_fields_and_manifest(
    storage: Storage,
) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    await storage.save_manifest(d.id, ["a.jpg", "b.jpg"])
    await storage.finish_job(d.id, exit_code=1, files_downloaded=1)
    await storage.mark_postprocess(d.id, "failed", chapters_packed=0, error="boom")

    assert await storage.reset_to_pending(d.id) is True

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.started_at is None
    assert fetched.finished_at is None
    assert fetched.exit_code is None
    assert fetched.files_downloaded == 0
    assert fetched.files_expected is None
    assert fetched.error is None
    assert fetched.postprocess_status is None
    assert fetched.postprocess_chapters_packed is None
    assert fetched.postprocess_error is None
    assert await storage.get_manifest(d.id) == []


async def test_reset_to_pending_refuses_non_terminal(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    # Still pending; reset must refuse.
    assert await storage.reset_to_pending(d.id) is False

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "pending"


async def test_reset_to_pending_accepts_cancelled(storage: Storage) -> None:
    d = await storage.insert_pending("https://example/x", "fake")
    assert await storage.cancel_pending(d.id) is True
    assert await storage.reset_to_pending(d.id) is True

    fetched = await storage.get(d.id)
    assert fetched is not None
    assert fetched.status == "pending"


async def test_manifest_cascades_on_download_delete(tmp_path: Path) -> None:
    """download_files has ON DELETE CASCADE; verify with a manual DELETE.

    The application never deletes downloads today, but the schema declares the
    constraint, so this guards against accidental removal of the cascade.
    """
    s = await Storage.open(tmp_path / "jobs.db")
    try:
        d = await s.insert_pending("https://example/x", "fake")
        await s.save_manifest(d.id, ["a.jpg"])
        # Enable FK enforcement (off by default in sqlite).
        await s._db.execute("PRAGMA foreign_keys = ON")  # type: ignore[attr-defined]
        await s._db.execute("DELETE FROM downloads WHERE id = ?", (d.id,))  # type: ignore[attr-defined]
        await s._db.commit()  # type: ignore[attr-defined]
        assert await s.get_manifest(d.id) == []
    finally:
        await s.close()
