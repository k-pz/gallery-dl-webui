from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from backend.database import open_database
from backend.targets import service as targets_service
from backend.targets.poller import _parse_iso, is_due
from backend.targets.schemas import Target


@pytest.fixture
async def db(tmp_path: Path):
    conn = await open_database(tmp_path / "jobs.db")
    try:
        yield conn
    finally:
        await conn.close()


def _t(**kwargs) -> Target:
    base = dict(
        id=1,
        url="https://x",
        name=None,
        extractor=None,
        output_dir=None,
        watched=True,
        watch_period=None,
        last_polled_at=None,
        created_at="2024-01-01T00:00:00+00:00",
    )
    base.update(kwargs)
    return Target(**base)


def test_is_due_unwatched_never_due() -> None:
    now = datetime.now(UTC)
    target = _t(watched=False)
    assert is_due(target, timedelta(hours=1), now) is False


def test_is_due_first_run_is_due() -> None:
    now = datetime.now(UTC)
    target = _t(last_polled_at=None)
    assert is_due(target, timedelta(hours=1), now) is True


def test_is_due_after_period_elapsed() -> None:
    now = datetime.now(UTC)
    old = (now - timedelta(hours=2)).isoformat()
    target = _t(last_polled_at=old, watch_period="1h")
    assert is_due(target, timedelta(days=1), now) is True


def test_is_due_within_period_not_due() -> None:
    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=30)).isoformat()
    target = _t(last_polled_at=recent, watch_period="1h")
    assert is_due(target, timedelta(days=1), now) is False


def test_is_due_falls_back_to_default_when_period_blank() -> None:
    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=30)).isoformat()
    target = _t(last_polled_at=recent, watch_period=None)
    assert is_due(target, timedelta(minutes=10), now) is True
    assert is_due(target, timedelta(hours=1), now) is False


def test_is_due_invalid_period_uses_default() -> None:
    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=30)).isoformat()
    target = _t(last_polled_at=recent, watch_period="not a duration")
    assert is_due(target, timedelta(minutes=10), now) is True


def test_parse_iso_assumes_utc_when_naive() -> None:
    dt = _parse_iso("2024-01-01T00:00:00")
    assert dt is not None
    assert dt.tzinfo is UTC


async def test_list_watched_targets_returns_watched_only(db: aiosqlite.Connection) -> None:
    a = await targets_service.upsert(db, "https://x/a", None, None)
    b = await targets_service.upsert(db, "https://x/b", None, None)
    await targets_service.upsert(db, "https://x/c", None, None)
    await targets_service.update(db, a.id, watched=True)
    await targets_service.update(db, b.id, watched=True)

    rows = await targets_service.list_watched(db)
    assert {r.id for r in rows} == {a.id, b.id}
