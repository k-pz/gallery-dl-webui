import aiosqlite

from backend.series_stats import service
from backend.targets import service as targets_service


async def test_save_reports_changes_only(db: aiosqlite.Connection) -> None:
    target = await targets_service.upsert(db, "https://example/x", "fake", None)
    stats = service.SeriesStats(chapter_count=12, epub_book_count=2, epub_pending_count=1)

    assert await service.get(db, target.id) is None
    assert await service.save(db, target.id, stats) is True
    assert await service.get(db, target.id) == stats
    assert await service.save(db, target.id, stats) is False

    grown = service.SeriesStats(chapter_count=13, epub_book_count=2, epub_pending_count=2)
    assert await service.save(db, target.id, grown) is True
    assert await service.get(db, target.id) == grown


async def test_stats_join_into_target_summary(db: aiosqlite.Connection) -> None:
    target = await targets_service.upsert(db, "https://example/x", "fake", None)
    listed = (await targets_service.list_all(db))[0]
    assert (listed.chapter_count, listed.epub_book_count, listed.epub_pending_count) == (
        None,
        None,
        None,
    )

    await service.save(db, target.id, service.SeriesStats(7, 1, 0))
    summary = await targets_service.get_summary(db, target.id)
    assert summary is not None
    assert (summary.chapter_count, summary.epub_book_count, summary.epub_pending_count) == (7, 1, 0)


async def test_save_skips_deleted_target_and_cascade_removes(db: aiosqlite.Connection) -> None:
    target = await targets_service.upsert(db, "https://example/x", "fake", None)
    await service.save(db, target.id, service.SeriesStats(1, 0, 0))
    await targets_service.delete(db, target.id)
    assert await service.get(db, target.id) is None
    assert await service.save(db, target.id, service.SeriesStats(2, 0, 0)) is False
