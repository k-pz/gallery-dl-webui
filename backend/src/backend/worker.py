import asyncio
import logging
from pathlib import Path

from backend import postprocess
from backend.gallery import Gallery
from backend.live_progress import LiveProgress
from backend.postprocess import FileRecord
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
        records: list[FileRecord] = []
        exit_code = 1
        try:
            relpaths = await asyncio.to_thread(self._gallery.extract_manifest, job.url)
            await self._storage.save_manifest(job.id, relpaths)
            await self._storage.mark_running(job.id)
            self._live.start(job.id)
            try:
                exit_code, records = await asyncio.to_thread(
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
            return

        if exit_code == 0:
            await self._run_postprocess(job, records, downloads_dir)

    async def _run_postprocess(
        self, job: Download, records: list[FileRecord], downloads_dir: Path
    ) -> None:
        cfg = await self._storage.get_app_config()
        output_dir_str = job.output_dir or cfg.get("postprocess_default_output_dir")
        root_str = cfg.get("postprocess_root")
        if not output_dir_str or not root_str:
            await self._storage.mark_postprocess(job.id, "skipped")
            return
        output_dir = Path(output_dir_str)
        root = Path(root_str).resolve()
        try:
            resolved = output_dir.resolve()
        except OSError as exc:
            await self._storage.mark_postprocess(job.id, "failed", error=repr(exc))
            return
        if resolved != root and root not in resolved.parents:
            await self._storage.mark_postprocess(
                job.id, "failed", error=f"output_dir {resolved} is not under root {root}"
            )
            return
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            await self._storage.mark_postprocess(job.id, "failed", error=repr(exc))
            return
        delete_raw = bool(cfg.get("delete_raw_after_pack", True))
        await self._storage.mark_postprocess(job.id, "running")
        try:
            result = await postprocess.run(records, output_dir, downloads_dir, delete_raw)
        except Exception as exc:
            logger.exception("postprocess for download %d failed", job.id)
            await self._storage.mark_postprocess(job.id, "failed", error=repr(exc))
            return
        status = "completed" if result.failed == 0 else "failed"
        await self._storage.mark_postprocess(
            job.id, status, chapters_packed=result.succeeded, error=result.error_summary
        )
