import asyncio
import logging
from pathlib import Path

import aiosqlite
from gallery_dl.exception import StopExtraction

from backend.app_config import service as app_config_service
from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
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
from backend.downloads.progress import count_present_chapters
from backend.events import EventBus, downloads_event, progress_event
from backend.targets import service as targets_service

logger = logging.getLogger(__name__)


class Worker:
    """Background coroutine that drains the `downloads` queue one job at a time.

    Strictly serial: one job in flight, ever. The loop calls
    `service.claim_next_pending` (atomic — see its docstring) to grab the
    next pending row, processes it to terminal, then loops.

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
        self._task: asyncio.Task[None] | None = None
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
        self._max_postprocess = DEFAULT_MAX_PARALLEL_POSTPROCESS

    def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._task = asyncio.create_task(self._run(), name="downloads-worker")

    async def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

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

    async def _run(self) -> None:
        """Read postprocess parallelism once, then loop on the queue.

        Live-reconfiguring `max_parallel_postprocess` would require restarting
        the worker — the user can bump the config and restart the service.
        """
        try:
            async with self._db_lock:
                cfg = await app_config_service.get_all(self._db)
        except Exception:
            cfg = {}
        post = _coerce_int(cfg.get("max_parallel_postprocess"), DEFAULT_MAX_PARALLEL_POSTPROCESS)
        self._max_postprocess = max(1, min(post, 16))

        while not self._stop.is_set():
            self._wakeup.clear()
            try:
                async with self._db_lock:
                    job = await service.claim_next_pending(self._db)
            except Exception:
                logger.exception("claim_next_pending failed")
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
        chapter_names: list[str] = []
        records: list[FileRecord] = []
        exit_code = 1
        cancelled = False
        # Shared across the worker thread (gallery-dl's per-file callback) and
        # the event loop (failure accounting). The set is only mutated from
        # the callback; the GIL covers it.
        chapters_seen: set[str] = set()
        try:
            skip_chapter = await self._build_skip_chapter(job)
            chapter_names = await self._extract_metadata(job, skip_chapter)
            if self._cancel_flags.get(job.id, False):
                async with self._db_lock:
                    await service.mark_cancelled(self._db, job.id, 0)
                self._publish(downloads_event("updated", id=job.id, status="cancelled"))
                return
            async with self._db_lock:
                await service.save_manifest(self._db, job.id, chapter_names)
            self._publish(downloads_event("manifest_ready", id=job.id, files=len(chapter_names)))
            try:
                exit_code, records, cancelled = await self._execute_download(
                    job, skip_chapter, chapters_seen
                )
            finally:
                self._live.clear(job.id)
        except Exception as exc:
            await self._handle_failure(job, exc, len(chapters_seen))
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

    async def _extract_metadata(
        self, job: Download, skip_chapter: SkipChapterFn | None
    ) -> list[str]:
        """Metadata-only pull: discover the chapter list and seed the target's
        series_name / status / tags. Skips the per-page enumeration the manifest
        sim does, so the worker can hand control to the actual download sooner.
        """
        meta = await asyncio.to_thread(self._gallery.extract_metadata, job.url)
        if job.target_id is not None and meta.series_name:
            async with self._db_lock:
                await targets_service.set_name(self._db, job.target_id, meta.series_name)
            self._publish(downloads_event("target_named", id=job.target_id, name=meta.series_name))
        if job.target_id is not None and meta.series_status:
            async with self._db_lock:
                await targets_service.set_series_status(self._db, job.target_id, meta.series_status)
        if job.target_id is not None and meta.series_tags:
            async with self._db_lock:
                await targets_service.set_series_tags(self._db, job.target_id, meta.series_tags)
        chapter_names: list[str] = []
        for (manga, chapter), _date in meta.chapter_dates.items():
            if skip_chapter is not None and manga and chapter and skip_chapter(manga, chapter):
                continue
            chapter_names.append(chapter)
        return chapter_names

    async def _execute_download(
        self,
        job: Download,
        skip_chapter: SkipChapterFn | None,
        chapters_seen: set[str],
    ) -> tuple[int, list[FileRecord], bool]:
        """Run the real download; return (exit_code, file records, was_cancelled).

        `chapters_seen` is mutated by the per-file callback so the caller can
        read a live chapter count even if `run_download` raises.
        """
        async with self._db_lock:
            await service.mark_running(self._db, job.id)
        self._publish(downloads_event("updated", id=job.id, status="running"))
        self._live.start(job.id)
        exit_code, records = await asyncio.to_thread(
            self._gallery.run_download,
            job.url,
            self._make_progress_cb(job.id, chapters_seen),
            skip_chapter,
        )
        cancelled = self._cancel_flags.get(job.id, False)
        # Prefer chapters_seen (populated by the per-file callback) over
        # `records` so the count stays correct when run_download surfaces no
        # records — e.g. extractors whose handle_url path doesn't reach
        # coerce_record_from_kwdict.
        present = max(len(chapters_seen), count_present_chapters([r.path for r in records]))
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

    async def _handle_failure(
        self, job: Download, exc: BaseException, chapters_present: int
    ) -> None:
        """Log + persist a job failure, recording chapters that landed before the
        failure (counted by the progress callback on the worker thread)."""
        logger.exception("download %d failed", job.id)
        async with self._db_lock:
            await service.mark_failed(self._db, job.id, repr(exc), chapters_present)
        self._publish(downloads_event("updated", id=job.id, status="failed"))

    def _make_progress_cb(self, job_id: int, chapters_seen: set[str]):
        # Raise StopExtraction so gallery-dl's own dispatcher catches it
        # and unwinds cleanly (it treats StopExtraction as a normal stop,
        # so job.run() still returns a status code).
        bus = self._bus
        loop = self._loop

        def cb(rel: str) -> None:
            if self._cancel_flags.get(job_id, False):
                raise StopExtraction()
            self._live.record(job_id, rel)
            chapters_seen.add(str(Path(rel).parent))
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
