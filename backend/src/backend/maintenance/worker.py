from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path

import aiosqlite

from backend.app_config import service as app_config_service
from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
    DEFAULT_READING_DIRECTION,
    READING_DIRECTIONS,
)
from backend.downloads import postprocess
from backend.downloads.postprocess import (
    SeriesMetadata,
    normalize_reading_direction,
    normalize_tags,
    sanitize,
)
from backend.maintenance import service
from backend.maintenance.live_progress import MaintenanceLiveProgress
from backend.targets import service as targets_service

logger = logging.getLogger(__name__)


class _JobProgressSink:
    """Adapter that funnels rename_packed_chapters callbacks into the live store."""

    def __init__(self, live: MaintenanceLiveProgress, job_id: int) -> None:
        self._live = live
        self._job_id = job_id

    def total(self, n: int) -> None:
        self._live.set_total(self._job_id, n)
        self._live.record(self._job_id, f"scanning… found {n} archive(s)")

    def step(self, line: str) -> None:
        self._live.increment_done(self._job_id)
        self._live.record(self._job_id, line)


class MaintenanceWorker:
    def __init__(self, db: aiosqlite.Connection, live: MaintenanceLiveProgress) -> None:
        self._db = db
        self._live = live
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="maintenance-worker")

    async def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def notify(self) -> None:
        self._wakeup.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._wakeup.clear()
            job = await service.claim_next_pending(self._db)
            if job is None:
                await self._wakeup.wait()
                continue
            self._live.start(job.id)
            try:
                result = await self._execute(job.kind, job.id)
            except Exception as exc:
                logger.exception("maintenance job %d failed", job.id)
                self._live.record(job.id, f"failed: {exc!r}")
                await service.mark_failed(self._db, job.id, repr(exc))
                self._live.clear(job.id)
                continue
            self._live.record(job.id, f"done: {result}")
            await service.mark_completed(self._db, job.id, result)
            self._live.clear(job.id)

    async def _execute(self, kind: str, job_id: int) -> dict[str, int]:
        if kind == "rename_chapters":
            return await self._run_rename(job_id)
        if kind == "regenerate_series_metadata":
            return await self._run_regenerate_metadata(job_id)
        raise ValueError(f"unsupported maintenance kind: {kind}")

    async def _run_rename(self, job_id: int) -> dict[str, int]:
        cfg = await app_config_service.get_all(self._db)
        root_str = cfg.get("postprocess_root")
        if not isinstance(root_str, str) or not root_str:
            raise ValueError("postprocess_root is not configured")
        template = cfg.get("chapter_naming_template")
        if not isinstance(template, str) or not template:
            template = DEFAULT_CHAPTER_NAMING_TEMPLATE
        sink = _JobProgressSink(self._live, job_id)
        result = await asyncio.to_thread(
            postprocess.rename_packed_chapters, Path(root_str), template, sink
        )
        return asdict(result)

    async def _run_regenerate_metadata(self, job_id: int) -> dict[str, int]:
        cfg = await app_config_service.get_all(self._db)
        root_str = cfg.get("postprocess_root")
        if not isinstance(root_str, str) or not root_str:
            raise ValueError("postprocess_root is not configured")
        default_direction = cfg.get("default_reading_direction")
        if (
            not isinstance(default_direction, str)
            or default_direction not in READING_DIRECTIONS
        ):
            default_direction = DEFAULT_READING_DIRECTION
        overrides_by_series = await self._build_series_overrides(default_direction)
        sink = _JobProgressSink(self._live, job_id)

        def lookup(series_name: str) -> SeriesMetadata | None:
            return overrides_by_series.get(sanitize(series_name).lower())

        result = await asyncio.to_thread(
            postprocess.regenerate_series_metadata, Path(root_str), lookup, sink
        )
        return asdict(result)

    async def _build_series_overrides(
        self, default_direction: str
    ) -> dict[str, SeriesMetadata]:
        """Index targets by sanitized series name so the regen pass can map
        CBZ-on-disk back to the user's tags + reading direction."""
        targets = await targets_service.list_all(self._db)
        result: dict[str, SeriesMetadata] = {}
        for summary in targets:
            target = summary.target
            if not target.name:
                continue
            key = sanitize(target.name).lower()
            result[key] = SeriesMetadata(
                name=target.name,
                tags=normalize_tags(list(target.tags)),
                reading_direction=normalize_reading_direction(
                    target.reading_direction or default_direction
                ),
            )
        return result
