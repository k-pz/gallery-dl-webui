"""Periodic watcher: re-queue downloads for watched targets whose period has elapsed.

The poller wakes on a fixed cadence (TICK_SECONDS), pulls every watched target,
and for each one whose `last_polled_at + period <= now` enqueues a fresh
download via Storage.insert_pending and nudges the Worker. The poller does not
itself run downloads — it only seeds them. If a target already has an in-flight
download we skip it: a single watched target should never have two concurrent
download rows.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from backend.durations import parse_duration
from backend.storage import Storage, Target
from backend.worker import Worker

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
        storage: Storage,
        worker: Worker,
        *,
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        self._storage = storage
        self._worker = worker
        self._tick = tick_seconds
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
        cfg = await self._storage.get_app_config()
        default_raw = cfg.get("default_watch_period")
        if not isinstance(default_raw, str) or not default_raw:
            default_raw = "1d"
        try:
            default_period = parse_duration(default_raw)
        except ValueError:
            default_period = timedelta(days=1)

        now = datetime.now(UTC)
        watched = await self._storage.list_watched_targets()
        notified = False
        for t in watched:
            if not is_due(t, default_period, now):
                continue
            if await self._storage.has_active_download_for_target(t.id):
                continue
            await self._storage.insert_pending(
                t.url, t.extractor, output_dir=t.output_dir, target_id=t.id
            )
            await self._storage.mark_target_polled(t.id)
            notified = True
            logger.info("poller queued target %d (%s)", t.id, t.url)
        if notified:
            self._worker.notify()
