"""Unit tests for targets service helpers that aren't covered via the router."""

import aiosqlite

from backend.targets import service as targets_service


async def test_set_series_published_at_fills_blank(db: aiosqlite.Connection) -> None:
    target = await targets_service.upsert(db, "https://example/x", "fake", None)
    assert target.series_published_at is None

    updated = await targets_service.set_series_published_at(db, target.id, "2015-05-01")
    assert updated is not None
    assert updated.series_published_at == "2015-05-01"


async def test_set_series_published_at_min_merges(db: aiosqlite.Connection) -> None:
    """A later date never overwrites; an earlier one does (older chapter surfaced)."""
    target = await targets_service.upsert(db, "https://example/x", "fake", None)
    await targets_service.set_series_published_at(db, target.id, "2015-05-01")

    # Later date (e.g. a partial upstream enumeration) is ignored.
    updated = await targets_service.set_series_published_at(db, target.id, "2020-01-01")
    assert updated is not None
    assert updated.series_published_at == "2015-05-01"

    # Earlier date moves the publication date back.
    updated = await targets_service.set_series_published_at(db, target.id, "2010-02-15")
    assert updated is not None
    assert updated.series_published_at == "2010-02-15"


async def test_set_series_published_at_empty_is_noop(db: aiosqlite.Connection) -> None:
    target = await targets_service.upsert(db, "https://example/x", "fake", None)
    await targets_service.set_series_published_at(db, target.id, "2015-05-01")

    updated = await targets_service.set_series_published_at(db, target.id, "")
    assert updated is not None
    assert updated.series_published_at == "2015-05-01"


async def test_update_sets_and_clears_metadata_source_url(db: aiosqlite.Connection) -> None:
    t = await targets_service.upsert(db, "https://example/s", "fake", None)
    updated = await targets_service.update(
        db, t.id, metadata_source_url="https://mangadex.org/title/abc"
    )
    assert updated is not None
    assert updated.metadata_source_url == "https://mangadex.org/title/abc"

    cleared = await targets_service.update(db, t.id, metadata_source_url=None)
    assert cleared is not None
    assert cleared.metadata_source_url is None
