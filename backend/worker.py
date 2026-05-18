from __future__ import annotations

import asyncio
import logging

from gallery_runtime import run_download
from log_hub import LogHub
from storage import Download, Storage

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, storage: Storage, hub: LogHub) -> None:
        self._storage = storage
        self._hub = hub
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
        counter = [0]

        def inc() -> None:
            counter[0] += 1

        self._hub.begin(job.id)
        try:
            exit_code = await asyncio.to_thread(run_download, job.url, inc)
            await self._storage.finish_job(job.id, exit_code, counter[0])
        except Exception as exc:
            logger.exception("download %d failed", job.id)
            await self._storage.mark_failed(job.id, repr(exc), counter[0])
        finally:
            self._hub.end(job.id)
