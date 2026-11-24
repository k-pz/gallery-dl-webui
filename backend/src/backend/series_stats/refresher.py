"""Background refresh of the cached series stats.

The refresher listens on the event bus and rescans a series when something
that can change its figures happens: one of its downloads settles, its
target row is edited (tags or reading direction change the EPUB
fingerprints), or — for every series — a maintenance job finishes or the
app config changes. All series are rescanned once at startup, which also
picks up files changed on disk while the app was down.

Rescans are debounced per series (a download emits several updates) and
run one at a time; the directory scan itself runs on a worker thread. When
a series' stats change, a `targets/stats` event tells clients to refetch
the library list.
"""

from __future__ import annotations

import asyncio
import logging

import aiosqlite

from backend.config import Settings
from backend.epub.state import load_state
from backend.events import Event, EventBus, targets_event
from backend.series_stats import service
from backend.targets import service as targets_service
from backend.tasks import log_task_death

logger = logging.getLogger(__name__)

DEBOUNCE_S = 2.0

# Maintenance job statuses after which files on disk may have changed.
_MAINTENANCE_SETTLED = frozenset({"completed", "failed", "cancelled"})


class SeriesStatsRefresher:
    def __init__(
        self,
        db: aiosqlite.Connection,
        settings: Settings,
        event_bus: EventBus,
        *,
        debounce_s: float = DEBOUNCE_S,
    ) -> None:
        self._db = db
        self._settings = settings
        self._bus = event_bus
        self._debounce_s = debounce_s
        # target id → loop time the rescan is due at.
        self._due: dict[int, float] = {}
        self._all_requested = False
        self._wakeup = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._subscribed = asyncio.Event()

    def start(self) -> None:
        for coro, name in (
            (self._listen(), "series-stats-listen"),
            (self._drain(), "series-stats"),
        ):
            task = asyncio.create_task(coro, name=name)
            task.add_done_callback(log_task_death)
            self._tasks.append(task)
        self.refresh_all()

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def wait_subscribed(self) -> None:
        """Resolves once the bus listener is attached (tests publish after it)."""
        await self._subscribed.wait()

    def refresh(self, target_id: int, *, delay: float | None = None) -> None:
        """Queue a rescan of one series, pushing back an already queued one."""
        wait = self._debounce_s if delay is None else delay
        self._due[target_id] = asyncio.get_running_loop().time() + wait
        self._wakeup.set()

    def refresh_all(self) -> None:
        self._all_requested = True
        self._wakeup.set()

    async def _listen(self) -> None:
        async with self._bus.subscribe() as queue:
            self._subscribed.set()
            while True:
                event = await queue.get()
                try:
                    await self._on_event(event)
                except Exception:
                    logger.exception(
                        "series stats: failed to handle %s/%s", event.topic, event.type
                    )

    async def _on_event(self, event: Event) -> None:
        topic, kind, data = event.topic, event.type, event.data
        if topic == "downloads" and kind == "updated" and isinstance(data.get("id"), int):
            async with self._db.execute(
                "SELECT target_id FROM downloads WHERE id = ?", (data["id"],)
            ) as cur:
                row = await cur.fetchone()
            if row is not None and row["target_id"] is not None:
                self.refresh(row["target_id"])
        elif topic == "targets" and kind == "updated" and isinstance(data.get("id"), int):
            self.refresh(data["id"])
        elif topic == "maintenance" and data.get("status") in _MAINTENANCE_SETTLED:
            self.refresh_all()
        elif topic == "config":
            self.refresh_all()

    async def _drain(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            if self._all_requested:
                self._all_requested = False
                async with self._db.execute("SELECT id FROM targets") as cur:
                    ids = [row["id"] for row in await cur.fetchall()]
                now = loop.time()
                for target_id in ids:
                    self._due.setdefault(target_id, now)
            if not self._due:
                await self._wakeup.wait()
                self._wakeup.clear()
                continue
            target_id, due = min(self._due.items(), key=lambda item: item[1])
            wait = due - loop.time()
            if wait > 0:
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=wait)
                except TimeoutError:
                    pass
                self._wakeup.clear()
                continue
            del self._due[target_id]
            try:
                await self._rescan(target_id)
            except Exception:
                logger.warning("series stats: rescan of target %d failed", target_id, exc_info=True)

    async def _rescan(self, target_id: int) -> None:
        target = await targets_service.get(self._db, target_id)
        if target is None:
            return
        state = await load_state(target, self._db, self._settings)
        if await service.save(self._db, target_id, service.stats_from_state(state)):
            self._bus.publish(targets_event("stats", id=target_id))
