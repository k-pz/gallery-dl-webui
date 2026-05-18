from __future__ import annotations

import asyncio
import logging

from gallery_runtime import count_present, extract_manifest, run_download
from settings import Settings
from storage import Download, Storage

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, storage: Storage, settings: Settings) -> None:
        self._storage = storage
        self._settings = settings
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="downloads-worker")

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
            job = await self._storage.claim_next_pending()
            if job is None:
                await self._wakeup.wait()
                continue
            await self._process(job)

    async def _process(self, job: Download) -> None:
        relpaths: list[str] = []
        try:
            relpaths = await asyncio.to_thread(extract_manifest, job.url)
            await self._storage.save_manifest(job.id, relpaths)
            await self._storage.mark_running(job.id)
            exit_code = await asyncio.to_thread(run_download, job.url)
            present = await asyncio.to_thread(count_present, relpaths)
            await self._storage.finish_job(job.id, exit_code, present)
        except Exception as exc:
            logger.exception("download %d failed", job.id)
            present = 0
            if relpaths:
                try:
                    present = await asyncio.to_thread(count_present, relpaths)
                except Exception:
                    present = 0
            await self._storage.mark_failed(job.id, repr(exc), present)
