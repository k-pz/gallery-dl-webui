import asyncio
import logging

from backend.gallery import Gallery
from backend.live_progress import LiveProgress
from backend.progress import count_present
from backend.storage import Download, Storage

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, storage: Storage, gallery: Gallery, live: LiveProgress) -> None:
        self._storage = storage
        self._gallery = gallery
        self._live = live
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
        downloads_dir = self._gallery.downloads_dir
        relpaths: list[str] = []
        try:
            relpaths = await asyncio.to_thread(self._gallery.extract_manifest, job.url)
            await self._storage.save_manifest(job.id, relpaths)
            await self._storage.mark_running(job.id)
            self._live.start(job.id)
            try:
                exit_code = await asyncio.to_thread(
                    self._gallery.run_download,
                    job.url,
                    lambda rel: self._live.record(job.id, rel),
                )
                present = await asyncio.to_thread(count_present, relpaths, downloads_dir)
                await self._storage.finish_job(job.id, exit_code, present)
            finally:
                self._live.clear(job.id)
        except Exception as exc:
            logger.exception("download %d failed", job.id)
            present = 0
            if relpaths:
                try:
                    present = await asyncio.to_thread(count_present, relpaths, downloads_dir)
                except Exception:
                    present = 0
            await self._storage.mark_failed(job.id, repr(exc), present)
