import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import aiosqlite
import pytest

from backend.config import Settings
from backend.events import Event, EventBus, maintenance_event, targets_event
from backend.series_stats import service
from backend.series_stats.refresher import SeriesStatsRefresher
from backend.targets import service as targets_service
from tests._helpers import write_chapter_cbz

SERIES = "Series"


async def _until(check: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.02)


@pytest.fixture
async def series(db: aiosqlite.Connection, tmp_path: Path) -> tuple[int, Path]:
    out = tmp_path / "manga"
    target = await targets_service.upsert(db, "https://example/s", "fake", str(out))
    await targets_service.set_name(db, target.id, SERIES)
    series_dir = out / SERIES
    for n in ("1", "2"):
        write_chapter_cbz(series_dir / f"{SERIES} - c{n}.cbz", SERIES, n)
    return target.id, series_dir


@pytest.fixture
async def refresher(
    db: aiosqlite.Connection, settings: Settings
) -> AsyncIterator[tuple[SeriesStatsRefresher, EventBus]]:
    bus = EventBus()
    r = SeriesStatsRefresher(db, settings, bus, debounce_s=0)
    r.start()
    await r.wait_subscribed()
    try:
        yield r, bus
    finally:
        await r.stop()


async def _chapters(db: aiosqlite.Connection, target_id: int) -> int | None:
    stats = await service.get(db, target_id)
    return stats.chapter_count if stats else None


async def test_scans_every_series_at_startup_and_publishes(
    db: aiosqlite.Connection,
    series: tuple[int, Path],
    settings: Settings,
) -> None:
    target_id, _ = series
    bus = EventBus()
    seen: list[Event] = []

    async def collect() -> None:
        async with bus.subscribe() as q:
            while True:
                seen.append(await q.get())

    collector = asyncio.create_task(collect())
    await asyncio.sleep(0)
    r = SeriesStatsRefresher(db, settings, bus, debounce_s=0)
    r.start()
    try:

        async def scanned() -> bool:
            return await _chapters(db, target_id) == 2

        await _until(scanned)
        await _until(lambda: _true(targets_event("stats", id=target_id) in seen))
    finally:
        await r.stop()
        collector.cancel()


async def _true(value: bool) -> bool:
    return value


async def test_target_update_triggers_rescan(
    db: aiosqlite.Connection,
    series: tuple[int, Path],
    refresher: tuple[SeriesStatsRefresher, EventBus],
) -> None:
    target_id, series_dir = series
    _, bus = refresher

    async def two() -> bool:
        return await _chapters(db, target_id) == 2

    await _until(two)
    write_chapter_cbz(series_dir / f"{SERIES} - c3.cbz", SERIES, "3")
    bus.publish(targets_event("updated", id=target_id))

    async def three() -> bool:
        return await _chapters(db, target_id) == 3

    await _until(three)


async def test_finished_maintenance_job_rescans_everything(
    db: aiosqlite.Connection,
    series: tuple[int, Path],
    refresher: tuple[SeriesStatsRefresher, EventBus],
) -> None:
    target_id, series_dir = series
    _, bus = refresher

    async def two() -> bool:
        return await _chapters(db, target_id) == 2

    await _until(two)
    (series_dir / f"{SERIES} - c2.cbz").unlink()
    # A running job doesn't trigger anything; a settled one does.
    bus.publish(maintenance_event("updated", id=1, status="completed"))

    async def one() -> bool:
        return await _chapters(db, target_id) == 1

    await _until(one)
