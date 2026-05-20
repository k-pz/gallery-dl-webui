"""Periodic watcher: re-queue downloads for watched targets whose period has elapsed.

The poller wakes on a fixed cadence (TICK_SECONDS), pulls every watched target,
and for each one whose `last_polled_at + period <= now` enqueues a fresh
download via downloads.service.insert_pending and nudges the Worker. The poller
does not itself run downloads — it only seeds them. If a target already has an
in-flight download we skip it: a single watched target should never have two
concurrent download rows.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import aiosqlite

from backend.app_config import service as app_config_service
from backend.downloads import service as downloads_service
from backend.downloads.worker import Worker
from backend.events import EventBus, downloads_event, targets_event
from backend.targets import service as targets_service
from backend.targets.models import Target
from backend.targets.utils import parse_duration

logger = logging.getLogger(__name__)

TICK_SECONDS = 30.0


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def is_due(target: Target, default_period: timedelta, now: datetime) -> bool:
    if not target.watched:
        return False
    raw = target.watch_period or ""
    if raw.strip():
        try:
            period = parse_duration(raw)
        except ValueError:
            logger.warning(
                "target %d has invalid watch_period %r — falling back to default",
                target.id,
                raw,
            )
            period = default_period
    else:
        period = default_period
    if target.last_polled_at is None:
        return True
    last = _parse_iso(target.last_polled_at)
    if last is None:
        return True
    return now - last >= period


class Poller:
    def __init__(
        self,
        db: aiosqlite.Connection,
        worker: Worker,
        *,
        tick_seconds: float = TICK_SECONDS,
        event_bus: EventBus | None = None,
        db_lock: asyncio.Lock | None = None,
    ) -> None:
        self._db = db
        self._worker = worker
        self._tick = tick_seconds
        self._bus = event_bus
        self._db_lock = db_lock or asyncio.Lock()
        self._stop = asyncio.Event()
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="poller")

    async def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def notify(self) -> None:
        """Wake the poller early — e.g. when a target's watch flag flips on."""
        self._wakeup.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick_once()
            except Exception:
                logger.exception("poller tick failed")
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=self._tick)
            except TimeoutError:
                pass
            self._wakeup.clear()

    async def _tick_once(self) -> None:
        async with self._db_lock:
            cfg = await app_config_service.get_all(self._db)
        default_raw = cfg.get("default_watch_period")
        if not isinstance(default_raw, str) or not default_raw:
            default_raw = "1d"
        try:
            default_period = parse_duration(default_raw)
        except ValueError:
            default_period = timedelta(days=1)

        now = datetime.now(UTC)
        async with self._db_lock:
            watched = await targets_service.list_watched(self._db)
        notified = False
        for t in watched:
            if not is_due(t, default_period, now):
                continue
            async with self._db_lock:
                if await downloads_service.has_active_for_target(self._db, t.id):
                    continue
                download = await downloads_service.insert_pending(
                    self._db, t.url, t.extractor, output_dir=t.output_dir, target_id=t.id
                )
                await targets_service.mark_polled(self._db, t.id)
            notified = True
            logger.info("poller queued target %d (%s)", t.id, t.url)
            if self._bus is not None:
                self._bus.publish(downloads_event("created", id=download.id))
                self._bus.publish(targets_event("updated", id=t.id))
        if notified:
            self._worker.notify()
