import aiosqlite

from backend.downloads import service


async def test_insert_pending_starts_in_pending_state(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")

    assert d.id > 0
    assert d.url == "https://example/x"
    assert d.extractor == "fake"
    assert d.status == "pending"
    assert d.started_at is None
    assert d.finished_at is None
    assert d.files_downloaded == 0
    assert d.files_expected is None


async def test_download_schema_exposes_new_count_fields(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    fetched = await service.get(db, d.id)
    assert fetched is not None
    # New optional fields default to None on a fresh row.
    assert fetched.chapters_discovered is None
    assert fetched.chapters_failed is None


async def test_get_returns_persisted_row(db: aiosqlite.Connection) -> None:
    inserted = await service.insert_pending(db, "https://example/x", None)
    fetched = await service.get(db, inserted.id)

    assert fetched is not None
    assert fetched.id == inserted.id
    assert fetched.extractor is None


async def test_get_missing_returns_none(db: aiosqlite.Connection) -> None:
    assert await service.get(db, 9999) is None


async def test_list_recent_orders_newest_first(db: aiosqlite.Connection) -> None:
    a = await service.insert_pending(db, "https://example/a", "fake")
    b = await service.insert_pending(db, "https://example/b", "fake")
    c = await service.insert_pending(db, "https://example/c", "fake")

    rows = await service.list_recent(db, 10)
    ids = [r.id for r in rows]

    assert ids == [c.id, b.id, a.id]


async def test_list_recent_respects_limit(db: aiosqlite.Connection) -> None:
    for i in range(5):
        await service.insert_pending(db, f"https://example/{i}", "fake")
    rows = await service.list_recent(db, 2)
    assert len(rows) == 2


async def test_claim_next_pending_advances_status(db: aiosqlite.Connection) -> None:
    first = await service.insert_pending(db, "https://example/a", "fake")
    second = await service.insert_pending(db, "https://example/b", "fake")

    claimed = await service.claim_next_pending(db)
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == "extracting"
    assert claimed.started_at is not None

    # The next claim picks the next pending row.
    claimed2 = await service.claim_next_pending(db)
    assert claimed2 is not None
    assert claimed2.id == second.id


async def test_claim_next_pending_returns_none_when_empty(db: aiosqlite.Connection) -> None:
    assert await service.claim_next_pending(db) is None


async def test_save_and_get_manifest(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2"])

    manifest = await service.get_manifest(db, d.id)
    fetched = await service.get(db, d.id)

    # The manifest now stores chapter names (one row per chapter), and
    # both files_expected and chapters_total carry the same count.
    assert manifest == ["1", "2"]
    assert fetched is not None
    assert fetched.files_expected == 2
    assert fetched.chapters_total == 2


async def test_save_manifest_counts_chapters(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2", "3", "4"])

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.chapters_total == 4
    assert fetched.files_expected == 4


async def test_save_manifest_replaces_existing(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2"])
    await service.save_manifest(db, d.id, ["3"])

    assert await service.get_manifest(db, d.id) == ["3"]
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.files_expected == 1
    assert fetched.chapters_total == 1


async def test_save_manifest_records_discovered_and_dates(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2"], dates={"1": "2026-01-01"}, discovered=5)
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.chapters_total == 2  # needed
    assert fetched.chapters_discovered == 5
    outcomes = await service.get_chapter_outcomes(db, d.id)
    assert [o.name for o in outcomes] == ["1", "2"]
    assert outcomes[0].status == "pending"
    assert outcomes[0].date == "2026-01-01"


async def test_save_chapter_outcomes_updates_rows_and_counts(db: aiosqlite.Connection) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2"], discovered=2)
    await service.save_chapter_outcomes(
        db,
        d.id,
        [
            ChapterOutcome("1", "downloaded", 12, "Intro", "2026-01-01", None),
            ChapterOutcome("2", "failed", 0, "", "", "403 Forbidden"),
        ],
    )
    rows = await service.get_chapter_outcomes(db, d.id)
    by_name = {r.name: r for r in rows}
    assert by_name["1"].status == "downloaded"
    assert by_name["1"].pages == 12
    assert by_name["1"].title == "Intro"
    assert by_name["2"].status == "failed"
    assert by_name["2"].error == "403 Forbidden"
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.chapters_failed == 1


async def test_save_chapter_outcomes_inserts_synthesized_chapter(db: aiosqlite.Connection) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, [], discovered=0)
    await service.save_chapter_outcomes(
        db, d.id, [ChapterOutcome("9", "downloaded", 3, "", "", None)]
    )
    rows = await service.get_chapter_outcomes(db, d.id)
    assert [r.name for r in rows] == ["9"]


async def test_reset_to_pending_clears_new_count_columns(db: aiosqlite.Connection) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1"], discovered=3)
    await service.save_chapter_outcomes(
        db, d.id, [ChapterOutcome("1", "failed", 0, "", "", "boom")]
    )
    await service.finish_job(db, d.id, exit_code=1, files_downloaded=0)
    assert await service.reset_to_pending(db, d.id) is True
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.chapters_discovered is None
    assert fetched.chapters_failed is None
    assert await service.get_chapter_outcomes(db, d.id) == []


async def test_mark_running(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.claim_next_pending(db)
    await service.mark_running(db, d.id)

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "running"


async def test_finish_job_zero_exit_marks_completed(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.finish_job(db, d.id, exit_code=0, files_downloaded=4)

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "completed"
    assert fetched.exit_code == 0
    assert fetched.files_downloaded == 4
    assert fetched.finished_at is not None


async def test_finish_job_nonzero_exit_marks_failed(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.finish_job(db, d.id, exit_code=1, files_downloaded=2)

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.exit_code == 1


async def test_mark_failed_records_error(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.mark_failed(db, d.id, "boom", files_downloaded=0)

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.error == "boom"


async def test_mark_interrupted_on_boot_only_affects_in_flight(db: aiosqlite.Connection) -> None:
    # Insert one row and claim it so it ends up in "extracting".
    extracting_row = await service.insert_pending(db, "https://example/x1", "fake")
    claimed = await service.claim_next_pending(db)
    assert claimed is not None and claimed.id == extracting_row.id

    # Another row that stays pending. claim_next_pending was already called, so
    # this one is left alone.
    pending_row = await service.insert_pending(db, "https://example/x2", "fake")

    # Running row.
    running_row = await service.insert_pending(db, "https://example/x3", "fake")
    await service.mark_running(db, running_row.id)

    # Completed row.
    completed_row = await service.insert_pending(db, "https://example/x4", "fake")
    await service.finish_job(db, completed_row.id, exit_code=0, files_downloaded=0)

    n = await service.mark_interrupted_on_boot(db)
    assert n == 2

    extr = await service.get(db, extracting_row.id)
    pend = await service.get(db, pending_row.id)
    run = await service.get(db, running_row.id)
    done = await service.get(db, completed_row.id)

    assert extr is not None and extr.status == "failed" and extr.error is not None
    assert run is not None and run.status == "failed" and run.error is not None
    assert pend is not None and pend.status == "pending"
    assert done is not None and done.status == "completed"


async def test_mark_postprocess_persists_state(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.mark_postprocess(db, d.id, "completed", chapters_packed=3, error=None)

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.postprocess_status == "completed"
    assert fetched.postprocess_chapters_packed == 3
    assert fetched.postprocess_error is None


async def test_cancel_pending_flips_status_atomically(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    assert await service.cancel_pending(db, d.id) is True

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "cancelled"
    assert fetched.finished_at is not None

    # Second call is a no-op (no longer pending).
    assert await service.cancel_pending(db, d.id) is False


async def test_cancel_pending_skips_already_running_rows(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.claim_next_pending(db)  # → extracting

    assert await service.cancel_pending(db, d.id) is False
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "extracting"


async def test_mark_cancelled_records_finished_at_and_files(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.claim_next_pending(db)
    await service.mark_cancelled(db, d.id, files_downloaded=3)

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "cancelled"
    assert fetched.files_downloaded == 3
    assert fetched.finished_at is not None


async def test_reset_to_pending_clears_terminal_fields_and_manifest(
    db: aiosqlite.Connection,
) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2"])
    await service.finish_job(db, d.id, exit_code=1, files_downloaded=1)
    await service.mark_postprocess(db, d.id, "failed", chapters_packed=0, error="boom")

    assert await service.reset_to_pending(db, d.id) is True

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.started_at is None
    assert fetched.finished_at is None
    assert fetched.exit_code is None
    assert fetched.files_downloaded == 0
    assert fetched.files_expected is None
    assert fetched.chapters_total is None
    assert fetched.error is None
    assert fetched.postprocess_status is None
    assert fetched.postprocess_chapters_packed is None
    assert fetched.postprocess_error is None
    assert await service.get_manifest(db, d.id) == []


async def test_reset_to_pending_refuses_non_terminal(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    # Still pending; reset must refuse.
    assert await service.reset_to_pending(db, d.id) is False

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "pending"


async def test_reset_to_pending_accepts_cancelled(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    assert await service.cancel_pending(db, d.id) is True
    assert await service.reset_to_pending(db, d.id) is True

    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.status == "pending"


async def test_save_manifest_persists_titles(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2"], titles={"1": "Intro"}, discovered=2)
    outcomes = await service.get_chapter_outcomes(db, d.id)
    by_name = {o.name: o for o in outcomes}
    assert by_name["1"].title == "Intro"
    assert by_name["2"].title == ""


async def test_outcome_with_empty_title_does_not_blank_seeded_title(
    db: aiosqlite.Connection,
) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1"], titles={"1": "Seeded"})
    await service.save_chapter_outcomes(db, d.id, [ChapterOutcome("1", "skipped", 0, "", "", None)])
    outcomes = await service.get_chapter_outcomes(db, d.id)
    assert outcomes[0].title == "Seeded"
