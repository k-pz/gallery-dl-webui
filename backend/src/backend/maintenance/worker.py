from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite

from backend.app_config import service as app_config_service
from backend.app_config.constants import DEFAULT_CHAPTER_NAMING_TEMPLATE
from backend.downloads import postprocess
from backend.maintenance import service

logger = logging.getLogger(__name__)


class MaintenanceWorker:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
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
            try:
                result = await self._execute(job.kind)
            except Exception as exc:
                logger.exception("maintenance job %d failed", job.id)
                await service.mark_failed(self._db, job.id, repr(exc))
                continue
            await service.mark_completed(self._db, job.id, result)

    async def _execute(self, kind: str) -> dict[str, int]:
        if kind != "rename_chapters":
            raise ValueError(f"unsupported maintenance kind: {kind}")
        cfg = await app_config_service.get_all(self._db)
        root_str = cfg.get("postprocess_root")
        if not isinstance(root_str, str) or not root_str:
            raise ValueError("postprocess_root is not configured")
        template = cfg.get("chapter_naming_template")
        if not isinstance(template, str) or not template:
            template = DEFAULT_CHAPTER_NAMING_TEMPLATE
        result = await asyncio.to_thread(
            postprocess.rename_packed_chapters, Path(root_str), template
        )
        return {"total": result.total, "renamed": result.renamed, "skipped": result.skipped}
