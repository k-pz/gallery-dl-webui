import asyncio
import logging
from pathlib import Path

import aiosqlite
from gallery_dl.exception import StopExtraction

from backend.app_config import service as app_config_service
from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
    DEFAULT_MAX_CONCURRENT_DOWNLOADS,
    DEFAULT_MAX_PARALLEL_POSTPROCESS,
    DEFAULT_READING_DIRECTION,
    READING_DIRECTIONS,
)
from backend.downloads import postprocess, service
from backend.downloads.gallery import Gallery, SkipChapterFn
from backend.downloads.live_progress import LiveProgress
from backend.downloads.models import Download
from backend.downloads.postprocess import (
    FileRecord,
    SeriesMetadata,
    chapter_already_packed,
    normalize_reading_direction,
    normalize_tags,
)
from backend.downloads.progress import count_present
from backend.events import EventBus, downloads_event, progress_event
from backend.targets import service as targets_service

logger = logging.getLogger(__name__)


class Worker:
    """Background coroutine pool that drains the `downloads` queue.

    `Worker` runs N "slots" (asyncio tasks) concurrently; each slot calls
    `service.claim_next_pending`, which is atomic (see its docstring) so two
    slots never end up on the same job. The pool size comes from
    `app_config.max_concurrent_downloads` when available, with a small default.

    `request_cancel(id)` signals a per-id flag the gallery-dl worker thread
    polls inside its per-file callback; the bool is single-writer (the event
    loop) / single-reader (the worker thread) so the GIL is the only sync we
    need.
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        gallery: Gallery,
        live: LiveProgress,
        event_bus: EventBus | None = None,
        db_lock: asyncio.Lock | None = None,
    ) -> None:
        self._db = db
        self._gallery = gallery
        self._live = live
        self._bus = event_bus
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        # Connection-wide lock. Shared with the maintenance worker + poller so
        # multi-statement transactions on the single aiosqlite connection
        # don't trip "SQL statements in progress" on concurrent commits.
        self._db_lock = db_lock or asyncio.Lock()
        # Per-job cancel flags. Keyed by download id while the job is in the
        # worker; cleared in the finally block. The dict is only mutated from
        # the asyncio loop; the bool value is also read from the gallery-dl
        # worker thread.
        self._cancel_flags: dict[int, bool] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_slots = DEFAULT_MAX_CONCURRENT_DOWNLOADS
        self._max_postprocess = DEFAULT_MAX_PARALLEL_POSTPROCESS

    def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        # Bootstrap reads max-concurrency from app_config, then keeps the slot
        # pool at that size. Doing this in a task avoids making start() async
        # and keeps the lifespan wiring identical to the old single-slot worker.
        self._tasks = [asyncio.create_task(self._supervisor(), name="downloads-worker-supervisor")]

    async def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

    def notify(self) -> None:
        self._wakeup.set()

    def request_cancel(self, id_: int) -> bool:
        """Flag an in-flight job for cancellation. Returns True if it matched."""
        if id_ in self._cancel_flags:
            self._cancel_flags[id_] = True
            return True
        return False

    def _publish(self, *args, **kwargs) -> None:
        if self._bus is None:
            return
        self._bus.publish(*args, **kwargs)

    async def _supervisor(self) -> None:
        """Read concurrency settings from app_config once, then spawn the slot pool.

        Each slot is a long-running coroutine; this task waits for them all to
        finish on shutdown. Live-reconfiguring the slot count would require
        more coordination — the user can bump max_concurrent_downloads in
        config and restart the service.
        """
        try:
            async with self._db_lock:
                cfg = await app_config_service.get_all(self._db)
        except Exception:
            cfg = {}
        slots = _coerce_int(cfg.get("max_concurrent_downloads"), DEFAULT_MAX_CONCURRENT_DOWNLOADS)
        self._max_slots = max(1, min(slots, 16))
        post = _coerce_int(cfg.get("max_parallel_postprocess"), DEFAULT_MAX_PARALLEL_POSTPROCESS)
        self._max_postprocess = max(1, min(post, 16))
        slot_tasks = [
            asyncio.create_task(self._slot_loop(i), name=f"downloads-worker-{i}")
            for i in range(self._max_slots)
        ]
        try:
            await asyncio.gather(*slot_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for t in slot_tasks:
                t.cancel()
            raise

    async def _slot_loop(self, slot_id: int) -> None:
        while not self._stop.is_set():
            self._wakeup.clear()
            try:
                async with self._db_lock:
                    job = await service.claim_next_pending(self._db)
            except Exception:
                logger.exception("claim_next_pending failed in slot %d", slot_id)
                await asyncio.sleep(1.0)
                continue
            if job is None:
                await self._wakeup.wait()
                continue
            self._cancel_flags[job.id] = False
            self._publish(downloads_event("updated", id=job.id, status="extracting"))
            try:
                await self._process(job)
            finally:
                self._cancel_flags.pop(job.id, None)

    async def _process(self, job: Download) -> None:
        relpaths: list[str] = []
        records: list[FileRecord] = []
        exit_code = 1
        cancelled = False
        try:
            skip_chapter = await self._build_skip_chapter(job)
            relpaths = await self._extract_manifest(job, skip_chapter)
            if self._cancel_flags.get(job.id, False):
                async with self._db_lock:
                    await service.mark_cancelled(self._db, job.id, 0)
                self._publish(downloads_event("updated", id=job.id, status="cancelled"))
                return
            async with self._db_lock:
                await service.save_manifest(self._db, job.id, relpaths)
            self._publish(downloads_event("manifest_ready", id=job.id, files=len(relpaths)))
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
                await targets_service.set_name(self._db, job.target_id, manga)
                self._publish(downloads_event("target_named", id=job.target_id, name=manga))

        if exit_code == 0 and not cancelled:
            await self._run_postprocess(job, records, self._gallery.downloads_dir)
        # Settled — emit a final updated event so subscribers fetch the fresh row.
        self._publish(downloads_event("updated", id=job.id))

    async def _build_skip_chapter(self, job: Download) -> SkipChapterFn | None:
        """Skip-callable for watched targets so subsequent polls don't re-pull
        chapters that already exist as CBZs in the postprocess output dir.

        Returns None (no skipping) unless: the download is tied to a watched
        target AND postprocess will run with a resolvable output_dir.
        """
        if job.target_id is None:
            return None
        async with self._db_lock:
            target = await targets_service.get(self._db, job.target_id)
        if target is None or not target.watched:
            return None
        async with self._db_lock:
            cfg = await app_config_service.get_all(self._db)
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
            async with self._db_lock:
                await targets_service.set_name(self._db, job.target_id, manifest.series_name)
            self._publish(
                downloads_event("target_named", id=job.target_id, name=manifest.series_name)
            )
        if job.target_id is not None and manifest.series_status:
            async with self._db_lock:
                await targets_service.set_series_status(
                    self._db, job.target_id, manifest.series_status
                )
        if job.target_id is not None and manifest.series_tags:
            async with self._db_lock:
                await targets_service.set_series_tags(self._db, job.target_id, manifest.series_tags)
        return manifest.paths

    async def _execute_download(
        self,
        job: Download,
        relpaths: list[str],
        skip_chapter: SkipChapterFn | None,
    ) -> tuple[int, list[FileRecord], bool]:
        """Run the real download; return (exit_code, file records, was_cancelled)."""
        async with self._db_lock:
            await service.mark_running(self._db, job.id)
        self._publish(downloads_event("updated", id=job.id, status="running"))
        self._live.start(job.id)
        try:
            exit_code, records = await asyncio.to_thread(
                self._gallery.run_download,
                job.url,
                self._make_progress_cb(job.id),
                skip_chapter,
            )
            cancelled = self._cancel_flags.get(job.id, False)
            present = await asyncio.to_thread(count_present, relpaths, self._gallery.downloads_dir)
            async with self._db_lock:
                if cancelled:
                    await service.mark_cancelled(self._db, job.id, present)
                else:
                    await service.finish_job(self._db, job.id, exit_code, present)
            if cancelled:
                self._publish(downloads_event("updated", id=job.id, status="cancelled"))
            else:
                terminal = "completed" if exit_code == 0 else "failed"
                self._publish(downloads_event("updated", id=job.id, status=terminal))
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
        async with self._db_lock:
            await service.mark_failed(self._db, job.id, repr(exc), present)
        self._publish(downloads_event("updated", id=job.id, status="failed"))

    def _make_progress_cb(self, job_id: int):
        # Raise StopExtraction so gallery-dl's own dispatcher catches it
        # and unwinds cleanly (it treats StopExtraction as a normal stop,
        # so job.run() still returns a status code).
        bus = self._bus
        loop = self._loop

        def cb(rel: str) -> None:
            if self._cancel_flags.get(job_id, False):
                raise StopExtraction()
            self._live.record(job_id, rel)
            if bus is not None and loop is not None:
                bus.publish_threadsafe(loop, progress_event(job_id, relpath=rel))

        return cb

    async def _run_postprocess(
        self, job: Download, records: list[FileRecord], downloads_dir: Path
    ) -> None:
        async with self._db_lock:
            cfg = await app_config_service.get_all(self._db)
        output_dir_str = job.output_dir or cfg.get("postprocess_default_output_dir")
        root_str = cfg.get("postprocess_root")
        if not output_dir_str or not root_str:
            async with self._db_lock:
                await service.mark_postprocess(self._db, job.id, "skipped")
            return
        output_dir = Path(output_dir_str)
        root = Path(root_str).resolve()
        try:
            resolved = output_dir.resolve()
        except OSError as exc:
            async with self._db_lock:
                await service.mark_postprocess(self._db, job.id, "failed", error=repr(exc))
            return
        if resolved != root and root not in resolved.parents:
            async with self._db_lock:
                await service.mark_postprocess(
                    self._db,
                    job.id,
                    "failed",
                    error=f"output_dir {resolved} is not under root {root}",
                )
            return
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            async with self._db_lock:
                await service.mark_postprocess(self._db, job.id, "failed", error=repr(exc))
            return
        delete_raw = bool(cfg.get("delete_raw_after_pack", True))
        naming_template = cfg.get("chapter_naming_template")
        if not isinstance(naming_template, str) or not naming_template:
            naming_template = DEFAULT_CHAPTER_NAMING_TEMPLATE
        metadata_overrides = await self._series_metadata_overrides(job, cfg)
        async with self._db_lock:
            await service.mark_postprocess(self._db, job.id, "running")
        self._publish(downloads_event("postprocess", id=job.id, status="running"))
        try:
            result = await postprocess.run(
                records,
                output_dir,
                downloads_dir,
                delete_raw,
                naming_template=naming_template,
                metadata_overrides=metadata_overrides,
                max_parallel=self._max_postprocess,
                on_chapter_done=lambda chapter, ok: self._publish(
                    progress_event(job.id, chapter=chapter, packed_ok=ok)
                ),
            )
        except Exception as exc:
            logger.exception("postprocess for download %d failed", job.id)
            async with self._db_lock:
                await service.mark_postprocess(self._db, job.id, "failed", error=repr(exc))
            self._publish(downloads_event("postprocess", id=job.id, status="failed"))
            return
        status = "completed" if result.failed == 0 else "failed"
        async with self._db_lock:
            await service.mark_postprocess(
                self._db,
                job.id,
                status,
                chapters_packed=result.succeeded,
                error=result.error_summary,
            )
        self._publish(downloads_event("postprocess", id=job.id, status=status))

    async def _series_metadata_overrides(
        self, job: Download, cfg: dict[str, object]
    ) -> SeriesMetadata:
        """Resolve tags + reading direction + series status for this job's target.

        Per-target settings win; otherwise we fall back to the config default
        (or the package-level default if config is missing the key). Status
        has no default — empty means series.json omits the field, which is
        what Komga reads as "unknown".
        """
        tags: list[str] = []
        reading_direction = cfg.get("default_reading_direction")
        if not isinstance(reading_direction, str) or reading_direction not in READING_DIRECTIONS:
            reading_direction = DEFAULT_READING_DIRECTION
        series_status = ""
        if job.target_id is not None:
            async with self._db_lock:
                target = await targets_service.get(self._db, job.target_id)
            if target is not None:
                tags = list(target.tags)
                if target.reading_direction:
                    reading_direction = target.reading_direction
                if target.series_status:
                    series_status = target.series_status
        return SeriesMetadata(
            tags=normalize_tags(tags),
            reading_direction=normalize_reading_direction(reading_direction),
            status=series_status,
        )


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default
