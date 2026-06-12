import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

import aiosqlite
from gallery_dl.exception import StopExtraction

from backend.app_config import service as app_config_service
from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
    DEFAULT_MAX_PARALLEL_POSTPROCESS,
    DEFAULT_READING_DIRECTION,
    MAX_PARALLEL_POSTPROCESS_CAP,
    READING_DIRECTIONS,
)
from backend.comic_metadata import (
    FileRecord,
    SeriesMetadata,
    normalize_reading_direction,
    normalize_tags,
)
from backend.downloads import postprocess, service
from backend.downloads.gallery import Gallery, SkipChapterFn
from backend.downloads.live_progress import LiveProgress
from backend.downloads.outcomes import ChapterSeed, reconcile_outcomes
from backend.downloads.postprocess import PackedChapterIndex, build_packed_chapter_index
from backend.downloads.progress import count_present_chapters
from backend.downloads.schemas import Download
from backend.events import EventBus, downloads_event, progress_event
from backend.targets import service as targets_service
from backend.tasks import log_task_death

logger = logging.getLogger(__name__)

# Minimum spacing between per-download progress events. Clients treat these
# purely as "refetch the progress endpoint now" hints, and a large series can
# complete many files per second — publishing one event per file floods the
# websocket and makes every connected client refetch (and re-render) the full
# chapter list per file, freezing the UI. Collapsing the stream to one event
# per interval is lossless: the terminal `downloads` event always triggers a
# final refetch, and the frontend keeps a slack fallback poll besides.
PROGRESS_EVENT_MIN_INTERVAL_S = 1.0


class _ProgressEventThrottle:
    """Leading-edge rate limiter for one job's progress events.

    Called from the gallery-dl worker thread and (separately) from the event
    loop during postprocess; never concurrently for the same instance, so the
    GIL-atomic float read/write needs no extra locking.
    """

    def __init__(
        self,
        interval_s: float = PROGRESS_EVENT_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval_s = interval_s
        self._clock = clock
        self._last: float | None = None

    def ready(self) -> bool:
        now = self._clock()
        if self._last is None or now - self._last >= self._interval_s:
            self._last = now
            return True
        return False


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
    ) -> None:
        self._db = db
        self._gallery = gallery
        self._live = live
        self._bus = event_bus
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        # Per-job cancel flags. Keyed by download id while the job is in the
        # worker; cleared in the finally block. The dict is only mutated from
        # the asyncio loop; the bool value is also read from the gallery-dl
        # worker thread.
        self._cancel_flags: dict[int, bool] = {}
        # Ids cancelled while not yet claimed: a cancel landing in the window
        # between the router's status read and the worker's claim would
        # otherwise miss both request_cancel and cancel_pending. Checked (and
        # drained) at claim time.
        self._requested_cancels: set[int] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_postprocess = DEFAULT_MAX_PARALLEL_POSTPROCESS

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run(), name="downloads-worker")
        self._task.add_done_callback(log_task_death)

    async def stop(self) -> None:
        self._stop.set()
        # Flag any in-flight job for cancellation so shutdown doesn't block
        # behind a multi-hour gallery-dl run; the job is marked cancelled the
        # same way a user-requested cancel would be.
        for job_id in self._cancel_flags:
            self._cancel_flags[job_id] = True
        self._wakeup.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def notify(self) -> None:
        self._wakeup.set()

    def discard_cancel_request(self, id_: int) -> None:
        """Forget a pre-claim cancel record (the job was requeued)."""
        self._requested_cancels.discard(id_)

    def request_cancel(self, id_: int) -> bool:
        """Flag an in-flight job for cancellation. Returns True if it matched.

        Ids that aren't in flight are remembered so a job claimed inside the
        router's check-then-signal window still gets cancelled at claim time.
        """
        if id_ in self._cancel_flags:
            self._cancel_flags[id_] = True
            return True
        self._requested_cancels.add(id_)
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
            cfg = await app_config_service.get_all(self._db)
        except Exception:
            cfg = {}
        self._max_postprocess = app_config_service.coerce_clamped_int(
            cfg.get("max_parallel_postprocess"),
            DEFAULT_MAX_PARALLEL_POSTPROCESS,
            lo=1,
            hi=MAX_PARALLEL_POSTPROCESS_CAP,
        )

        while not self._stop.is_set():
            self._wakeup.clear()
            try:
                job = await service.claim_next_pending(self._db)
            except Exception:
                logger.exception("claim_next_pending failed")
                await asyncio.sleep(1.0)
                continue
            if job is None:
                await self._wakeup.wait()
                continue
            if job.id in self._requested_cancels:
                # Cancel arrived between the router's status read and our
                # claim — honour it before doing any work.
                self._requested_cancels.discard(job.id)
                try:
                    await service.mark_cancelled(self._db, job.id, 0)
                except Exception:
                    logger.exception("failed to mark pre-claim cancel for %d", job.id)
                self._publish(downloads_event("updated", id=job.id, status="cancelled"))
                continue
            self._cancel_flags[job.id] = False
            self._publish(downloads_event("updated", id=job.id, status="extracting"))
            try:
                await self._process(job)
            except Exception:
                # _process persists its own failures; this guards the tail
                # work after that handler (target naming, postprocess
                # bookkeeping) so one transient DB/OS error can't kill the
                # worker task and stall the queue for good.
                logger.exception("unhandled error processing download %d", job.id)
            finally:
                self._cancel_flags.pop(job.id, None)

    async def _process(self, job: Download) -> None:
        needed: list[ChapterSeed] = []
        records: list[FileRecord] = []
        exit_code = 1
        cancelled = False
        # Shared across the worker thread (gallery-dl's per-file callback) and
        # the event loop (failure accounting). The set is only mutated from
        # the callback; the GIL covers it.
        chapters_seen: set[str] = set()
        try:
            skip_chapter = await self._build_skip_chapter(job)
            needed, discovered = await self._extract_metadata(job, skip_chapter)
            if self._cancel_flags.get(job.id, False):
                await service.mark_cancelled(self._db, job.id, 0)
                self._publish(downloads_event("updated", id=job.id, status="cancelled"))
                return
            await service.save_manifest(
                self._db,
                job.id,
                [s.name for s in needed],
                dates={s.name: s.date for s in needed if s.date},
                titles={s.name: s.title for s in needed if s.title},
                discovered=discovered,
            )
            self._publish(downloads_event("manifest_ready", id=job.id, files=len(needed)))
            try:
                exit_code, records, cancelled = await self._execute_download(
                    job, skip_chapter, chapters_seen, needed
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
        target = await targets_service.get(self._db, job.target_id)
        if target is None or not target.watched:
            return None
        cfg = await app_config_service.get_all(self._db)
        output_dir_str = job.output_dir or cfg.get("postprocess_default_output_dir")
        if not isinstance(output_dir_str, str) or not output_dir_str:
            return None
        output_dir = Path(output_dir_str)
        # One packed-chapter index per series, built lazily with a single
        # directory scan. The callable does zip + XML I/O (often against a
        # network mount) so it must only run off the event loop: the manifest
        # filter threads it via `_filter_needed_chapters`, and during the real
        # download gallery-dl calls it from its worker thread.
        indexes: dict[str, PackedChapterIndex] = {}

        def skip(manga: str, chapter: str) -> bool:
            index = indexes.get(manga)
            if index is None:
                index = build_packed_chapter_index(output_dir, manga)
                indexes[manga] = index
            return index.contains(chapter)

        return skip

    async def _extract_metadata(
        self, job: Download, skip_chapter: SkipChapterFn | None
    ) -> tuple[list[ChapterSeed], int]:
        """Metadata-only pull: discover the chapter list (+ release dates) and
        seed the target's series_name / status / tags. Returns the needed
        chapters (after skip-filtering) with their dates, plus the total
        discovered count.
        """
        meta = await asyncio.to_thread(self._gallery.extract_metadata, job.url)
        if job.target_id is not None and meta.series_name:
            await targets_service.set_name(self._db, job.target_id, meta.series_name)
            self._publish(downloads_event("target_named", id=job.target_id, name=meta.series_name))
        if job.target_id is not None and meta.series_status:
            await targets_service.set_series_status(self._db, job.target_id, meta.series_status)
        if job.target_id is not None and meta.series_tags:
            await targets_service.set_series_tags(self._db, job.target_id, meta.series_tags)
        if job.target_id is not None and meta.earliest_chapter_date:
            await targets_service.set_series_published_at(
                self._db, job.target_id, meta.earliest_chapter_date
            )
        needed = await asyncio.to_thread(
            _filter_needed_chapters, meta.chapter_dates, meta.chapter_titles, skip_chapter
        )
        return needed, len(meta.chapter_dates)

    async def _execute_download(
        self,
        job: Download,
        skip_chapter: SkipChapterFn | None,
        chapters_seen: set[str],
        needed: list[ChapterSeed],
    ) -> tuple[int, list[FileRecord], bool]:
        """Run the real download; reconcile + persist per-chapter outcomes;
        return (exit_code, file records, was_cancelled).

        `chapters_seen` is mutated by the per-file callback so the caller can
        read a live chapter count even if `run_download` raises.
        """
        await service.mark_running(self._db, job.id)
        self._publish(downloads_event("updated", id=job.id, status="running"))
        self._live.start(job.id)
        exit_code, records, chapter_errors = await asyncio.to_thread(
            self._gallery.run_download,
            job.url,
            self._make_progress_cb(job.id, chapters_seen),
            skip_chapter,
        )
        cancelled = self._cancel_flags.get(job.id, False)
        outcomes = reconcile_outcomes(needed, records, chapter_errors, exit_code)
        await service.save_chapter_outcomes(self._db, job.id, outcomes)
        present = sum(1 for o in outcomes if o.status == "downloaded")
        if not present:
            # Fall back to the live/record-derived count when reconciliation
            # produced no downloaded rows (e.g. extractors with empty chapter
            # metadata and no records keyed by chapter).
            present = max(len(chapters_seen), count_present_chapters([r.path for r in records]))
        if cancelled:
            await service.mark_cancelled(self._db, job.id, present)
            self._publish(downloads_event("updated", id=job.id, status="cancelled"))
        else:
            await service.finish_job(self._db, job.id, exit_code, present)
            terminal = "completed" if exit_code == 0 else "failed"
            self._publish(downloads_event("updated", id=job.id, status=terminal))
        return exit_code, records, cancelled

    async def _handle_failure(
        self, job: Download, exc: BaseException, chapters_present: int
    ) -> None:
        """Log + persist a job failure, recording chapters that landed before the
        failure (counted by the progress callback on the worker thread)."""
        logger.exception("download %d failed", job.id)
        await service.mark_failed(self._db, job.id, repr(exc), chapters_present)
        self._publish(downloads_event("updated", id=job.id, status="failed"))

    def _make_progress_cb(self, job_id: int, chapters_seen: set[str]):
        # Raise StopExtraction so gallery-dl's own dispatcher catches it
        # and unwinds cleanly (it treats StopExtraction as a normal stop,
        # so job.run() still returns a status code).
        bus = self._bus
        loop = self._loop
        throttle = _ProgressEventThrottle()

        def cb(rel: str) -> None:
            if self._cancel_flags.get(job_id, False):
                raise StopExtraction()
            self._live.record(job_id, rel)
            chapters_seen.add(str(Path(rel).parent))
            if bus is not None and loop is not None and throttle.ready():
                bus.publish_threadsafe(loop, progress_event(job_id, relpath=rel))

        return cb

    async def _run_postprocess(
        self, job: Download, records: list[FileRecord], downloads_dir: Path
    ) -> None:
        cfg = await app_config_service.get_all(self._db)
        output_dir_str = job.output_dir or cfg.get("postprocess_default_output_dir")
        root_str = cfg.get("postprocess_root")
        if not output_dir_str or not root_str:
            await service.mark_postprocess(self._db, job.id, "skipped")
            return
        output_dir = Path(output_dir_str)
        root = Path(root_str).resolve()
        try:
            resolved = output_dir.resolve()
        except OSError as exc:
            await service.mark_postprocess(self._db, job.id, "failed", error=repr(exc))
            return
        if resolved != root and root not in resolved.parents:
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
            await service.mark_postprocess(self._db, job.id, "failed", error=repr(exc))
            return
        delete_raw = bool(cfg.get("delete_raw_after_pack", True))
        naming_template = cfg.get("chapter_naming_template")
        if not isinstance(naming_template, str) or not naming_template:
            naming_template = DEFAULT_CHAPTER_NAMING_TEMPLATE
        metadata_overrides = await self._series_metadata_overrides(job, cfg)
        await service.mark_postprocess(self._db, job.id, "running")
        self._publish(downloads_event("postprocess", id=job.id, status="running"))
        throttle = _ProgressEventThrottle()

        def on_chapter_done(chapter: str, ok: bool) -> None:
            if throttle.ready():
                self._publish(progress_event(job.id, chapter=chapter, packed_ok=ok))

        try:
            result = await postprocess.run(
                records,
                output_dir,
                downloads_dir,
                delete_raw,
                naming_template=naming_template,
                metadata_overrides=metadata_overrides,
                max_parallel=self._max_postprocess,
                on_chapter_done=on_chapter_done,
            )
        except Exception as exc:
            logger.exception("postprocess for download %d failed", job.id)
            await service.mark_postprocess(self._db, job.id, "failed", error=repr(exc))
            self._publish(downloads_event("postprocess", id=job.id, status="failed"))
            return
        status = "completed" if result.failed == 0 else "failed"
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
        what Komga reads as "unknown". The stored first-publication date is
        threaded through so an incremental download (whose records only cover
        the new chapters) doesn't restamp series.json with the latest
        chapter's year.
        """
        tags: list[str] = []
        reading_direction = cfg.get("default_reading_direction")
        if not isinstance(reading_direction, str) or reading_direction not in READING_DIRECTIONS:
            reading_direction = DEFAULT_READING_DIRECTION
        series_status = ""
        published_at = ""
        if job.target_id is not None:
            target = await targets_service.get(self._db, job.target_id)
            if target is not None:
                tags = list(target.tags)
                if target.reading_direction:
                    reading_direction = target.reading_direction
                if target.series_status:
                    series_status = target.series_status
                if target.series_published_at:
                    published_at = target.series_published_at
        return SeriesMetadata(
            tags=normalize_tags(tags),
            reading_direction=normalize_reading_direction(reading_direction),
            status=series_status,
            published_at=published_at,
        )


def _filter_needed_chapters(
    chapter_dates: dict[tuple[str, str], str],
    chapter_titles: dict[tuple[str, str], str],
    skip_chapter: SkipChapterFn | None,
) -> list[ChapterSeed]:
    """Drop chapters the skip callable says are already packed as CBZs.

    Runs on a thread: the skip callable reads archives under the postprocess
    output dir (potentially a slow network mount), and a large series checks
    hundreds of chapters — that I/O must never block the event loop.
    """
    needed: list[ChapterSeed] = []
    for (manga, chapter), date in chapter_dates.items():
        if skip_chapter is not None and manga and chapter and skip_chapter(manga, chapter):
            continue
        needed.append(
            ChapterSeed(name=chapter, date=date, title=chapter_titles.get((manga, chapter), ""))
        )
    return needed
