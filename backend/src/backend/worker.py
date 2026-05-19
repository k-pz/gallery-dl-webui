import asyncio
import logging
from pathlib import Path

from gallery_dl.exception import StopExtraction

from backend import postprocess
from backend.gallery import Gallery, SkipChapterFn
from backend.live_progress import LiveProgress
from backend.postprocess import FileRecord, chapter_already_packed
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
        # The worker processes one job at a time, so cancel state is a single
        # bool: True iff request_cancel() fired for the current _current_id.
        # Read from the gallery-dl worker thread, written from the asyncio
        # loop — bool read/write is GIL-atomic, the only sync we need.
        self._current_id: int | None = None
        self._cancel_requested: bool = False

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

    def request_cancel(self, id_: int) -> bool:
        """Flag the in-flight job for cancellation. Returns True if it matched."""
        if self._current_id == id_:
            self._cancel_requested = True
            return True
        return False

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._wakeup.clear()
            job = await self._storage.claim_next_pending()
            if job is None:
                await self._wakeup.wait()
                continue
            self._current_id = job.id
            self._cancel_requested = False
            try:
                await self._process(job)
            finally:
                self._cancel_requested = False
                self._current_id = None

    async def _process(self, job: Download) -> None:
        relpaths: list[str] = []
        records: list[FileRecord] = []
        exit_code = 1
        cancelled = False
        try:
            skip_chapter = await self._build_skip_chapter(job)
            relpaths = await self._extract_manifest(job, skip_chapter)
            if self._cancel_requested:
                await self._storage.mark_cancelled(job.id, 0)
                return
            await self._storage.save_manifest(job.id, relpaths)
            exit_code, records, cancelled = await self._execute_download(
                job, relpaths, skip_chapter
            )
        except Exception as exc:
            await self._handle_failure(job, exc, relpaths)
            return

        # The simulation pass's series_name can be approximate; the real download
        # yields better metadata. Refine the target name if records carry one.
        if records and job.target_id is not None:
            manga = next((r.manga for r in records if r.manga), None)
            if manga:
                await self._storage.set_target_name(job.target_id, manga)

        if exit_code == 0 and not cancelled:
            await self._run_postprocess(job, records, self._gallery.downloads_dir)

    async def _build_skip_chapter(self, job: Download) -> SkipChapterFn | None:
        """Skip-callable for watched targets so subsequent polls don't re-pull
        chapters that already exist as CBZs in the postprocess output dir.

        Returns None (no skipping) unless: the download is tied to a watched
        target AND postprocess will run with a resolvable output_dir.
        """
        if job.target_id is None:
            return None
        target = await self._storage.get_target(job.target_id)
        if target is None or not target.watched:
            return None
        cfg = await self._storage.get_app_config()
        output_dir_str = job.output_dir or cfg.get("postprocess_default_output_dir")
        if not isinstance(output_dir_str, str) or not output_dir_str:
            return None
        output_dir = Path(output_dir_str)
        # Memoise per (manga, chapter) — gallery-dl calls into this once per
        # page URL, but the answer is the same for every page in a chapter.
        cache: dict[tuple[str, str], bool] = {}

        def skip(manga: str, chapter: str) -> bool:
            key = (manga, chapter)
            if key not in cache:
                cache[key] = chapter_already_packed(output_dir, manga, chapter)
            return cache[key]

        return skip

    async def _extract_manifest(
        self, job: Download, skip_chapter: SkipChapterFn | None
    ) -> list[str]:
        """Sim-run to discover expected file paths and capture an early series_name."""
        manifest = await asyncio.to_thread(self._gallery.extract_manifest, job.url, skip_chapter)
        if job.target_id is not None and manifest.series_name:
            await self._storage.set_target_name(job.target_id, manifest.series_name)
        return manifest.paths

    async def _execute_download(
        self,
        job: Download,
        relpaths: list[str],
        skip_chapter: SkipChapterFn | None,
    ) -> tuple[int, list[FileRecord], bool]:
        """Run the real download; return (exit_code, file records, was_cancelled)."""
        await self._storage.mark_running(job.id)
        self._live.start(job.id)
        try:
            exit_code, records = await asyncio.to_thread(
                self._gallery.run_download,
                job.url,
                self._make_progress_cb(job.id),
                skip_chapter,
            )
            cancelled = self._cancel_requested
            present = await asyncio.to_thread(count_present, relpaths, self._gallery.downloads_dir)
            if cancelled:
                await self._storage.mark_cancelled(job.id, present)
            else:
                await self._storage.finish_job(job.id, exit_code, present)
            return exit_code, records, cancelled
        finally:
            self._live.clear(job.id)

    async def _handle_failure(self, job: Download, exc: BaseException, relpaths: list[str]) -> None:
        """Log + persist a job failure, counting whatever files made it to disk."""
        logger.exception("download %d failed", job.id)
        present = 0
        if relpaths:
            try:
                present = await asyncio.to_thread(
                    count_present, relpaths, self._gallery.downloads_dir
                )
            except Exception:
                present = 0
        await self._storage.mark_failed(job.id, repr(exc), present)

    def _make_progress_cb(self, job_id: int):
        # Raise StopExtraction so gallery-dl's own dispatcher catches it
        # and unwinds cleanly (it treats StopExtraction as a normal stop,
        # so job.run() still returns a status code).
        def cb(rel: str) -> None:
            if self._cancel_requested:
                raise StopExtraction()
            self._live.record(job_id, rel)

        return cb

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
