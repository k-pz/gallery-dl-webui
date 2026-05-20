from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from backend.app_config import service as app_config_service
from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
    DEFAULT_READING_DIRECTION,
    READING_DIRECTIONS,
)
from backend.downloads import postprocess
from backend.downloads import service as downloads_service
from backend.downloads.postprocess import (
    MaintenanceCancelled,
    SeriesMetadata,
    normalize_reading_direction,
    normalize_tags,
    sanitize,
)
from backend.maintenance import service
from backend.maintenance.live_progress import MaintenanceLiveProgress
from backend.targets import service as targets_service

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.downloads.worker import Worker

logger = logging.getLogger(__name__)


def _exclude_dirs(cfg: dict[str, object]) -> list[str]:
    """Pull the user-configured directory-name exclusions out of app_config."""
    raw = cfg.get("postprocess_excluded_dir_names")
    if not isinstance(raw, list):
        return []
    return [name for name in raw if isinstance(name, str) and name]


def _unlink_if_exists(path: Path) -> bool:
    if path.exists():
        path.unlink()
        return True
    return False


def _wipe_directory_contents(root: Path, excluded_lower: set[str]) -> int:
    """Recursively remove children of `root`, returning the count touched.

    Direct children whose lowercased name is in `excluded_lower` are kept
    intact — the rebuild job leans on this to spare NAS trash dirs
    (#recycle, @eaDir, …) from a top-level wipe.
    """
    if not root.exists() or not root.is_dir():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.name.lower() in excluded_lower:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                continue
        removed += 1
    return removed


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
    def __init__(
        self,
        db: aiosqlite.Connection,
        live: MaintenanceLiveProgress,
        *,
        settings: Settings | None = None,
        downloads_worker: Worker | None = None,
    ) -> None:
        self._db = db
        self._live = live
        # Optional because the rebuild kind is the only one that needs to
        # touch disk + the downloads queue; the rename/regen kinds work with
        # just the db. Tests can therefore still construct the worker bare.
        self._settings = settings
        self._downloads_worker = downloads_worker
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        # The worker processes one maintenance job at a time, so the cancel
        # signal is a single bool keyed off the currently-running job id.
        # Read from the worker thread (via the should_cancel callable handed
        # to postprocess); written from the asyncio loop. Bool read/write is
        # GIL-atomic, which is all the sync we need.
        self._current_id: int | None = None
        self._cancel_requested: bool = False

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

    def request_cancel(self, id_: int) -> bool:
        """Flag the in-flight maintenance job for cancellation. Returns True if it matched."""
        if self._current_id == id_:
            self._cancel_requested = True
            return True
        return False

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._wakeup.clear()
            job = await service.claim_next_pending(self._db)
            if job is None:
                await self._wakeup.wait()
                continue
            self._current_id = job.id
            self._cancel_requested = False
            self._live.start(job.id)
            try:
                result = await self._execute(job.kind, job.id)
            except MaintenanceCancelled as cancelled:
                logger.info("maintenance job %d cancelled", job.id)
                self._live.record(job.id, f"cancelled: {cancelled.partial}")
                await service.mark_cancelled(self._db, job.id, cancelled.partial)
                self._live.clear(job.id)
                self._current_id = None
                self._cancel_requested = False
                continue
            except Exception as exc:
                logger.exception("maintenance job %d failed", job.id)
                self._live.record(job.id, f"failed: {exc!r}")
                await service.mark_failed(self._db, job.id, repr(exc))
                self._live.clear(job.id)
                self._current_id = None
                self._cancel_requested = False
                continue
            self._live.record(job.id, f"done: {result}")
            await service.mark_completed(self._db, job.id, result)
            self._live.clear(job.id)
            self._current_id = None
            self._cancel_requested = False

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    async def _execute(self, kind: str, job_id: int) -> dict[str, int]:
        if kind == "rename_chapters":
            return await self._run_rename(job_id)
        if kind == "regenerate_series_metadata":
            return await self._run_regenerate_metadata(job_id)
        if kind == "rebuild_library":
            return await self._run_rebuild_library(job_id)
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
        exclude_dirs = _exclude_dirs(cfg)
        result = await asyncio.to_thread(
            postprocess.rename_packed_chapters,
            Path(root_str),
            template,
            sink,
            self._should_cancel,
            exclude_dirs,
        )
        return asdict(result)

    async def _run_regenerate_metadata(self, job_id: int) -> dict[str, int]:
        cfg = await app_config_service.get_all(self._db)
        root_str = cfg.get("postprocess_root")
        if not isinstance(root_str, str) or not root_str:
            raise ValueError("postprocess_root is not configured")
        default_direction = cfg.get("default_reading_direction")
        if not isinstance(default_direction, str) or default_direction not in READING_DIRECTIONS:
            default_direction = DEFAULT_READING_DIRECTION
        overrides_by_series = await self._build_series_overrides(default_direction)
        sink = _JobProgressSink(self._live, job_id)

        def lookup(series_name: str) -> SeriesMetadata | None:
            return overrides_by_series.get(sanitize(series_name).lower())

        exclude_dirs = _exclude_dirs(cfg)
        result = await asyncio.to_thread(
            postprocess.regenerate_series_metadata,
            Path(root_str),
            lookup,
            sink,
            self._should_cancel,
            exclude_dirs,
        )
        return asdict(result)

    async def _run_rebuild_library(self, job_id: int) -> dict[str, int]:
        """Wipe downloads + output dirs, then re-enqueue every target as fresh.

        Targets stay in place (they're the source-of-truth library); what we
        drop is the download history, the gallery-dl archive (so it re-pulls
        every chapter), and the on-disk CBZ output. After the wipe we schedule
        one pending download per target so the worker re-runs them from zero.
        """
        if self._settings is None or self._downloads_worker is None:
            raise ValueError("rebuild_library requires settings + downloads worker")
        cfg = await app_config_service.get_all(self._db)
        excluded = {name.lower() for name in _exclude_dirs(cfg)}

        sink = _JobProgressSink(self._live, job_id)
        # Snapshot the library first — the upcoming wipe touches downloads
        # only, but we still want the count up front for the progress bar.
        targets = await targets_service.list_all(self._db)
        # 3 phases per target overhead (wipe, output-dir prune, re-enqueue) is
        # too lumpy for a meaningful total — surface a target-count instead.
        sink.total(len(targets))

        # Phase 1: wipe download history (preserves targets + app_config + the
        # in-flight maintenance job row).
        self._live.record(job_id, "wiping download history…")
        deleted_downloads = await downloads_service.delete_all(self._db)
        self._live.record(job_id, f"deleted {deleted_downloads} download rows")
        if self._should_cancel():
            raise MaintenanceCancelled(
                {"targets": len(targets), "deleted_downloads": deleted_downloads}
            )

        # Phase 2: wipe gallery-dl archive + the raw downloads dir so the next
        # run re-fetches everything (gallery-dl's archive is what short-circuits
        # repeat pulls; without dropping it the re-enqueue would be a no-op).
        archive_path = self._settings.archive_db_path
        archive_removed = await asyncio.to_thread(_unlink_if_exists, archive_path)
        if archive_removed:
            self._live.record(job_id, f"removed archive: {archive_path}")
        downloads_removed = await asyncio.to_thread(
            _wipe_directory_contents, self._settings.downloads_dir, set()
        )
        self._live.record(job_id, f"removed {downloads_removed} raw download entries")
        if self._should_cancel():
            raise MaintenanceCancelled(
                {"targets": len(targets), "deleted_downloads": deleted_downloads}
            )

        # Phase 3: wipe the postprocess output root if configured. Excluded
        # names (NAS trash etc.) survive the wipe so we don't tank a
        # /mnt/nas/Media root with a #recycle bin somebody actually cares
        # about. Skipped silently when no root is set.
        output_removed = 0
        root_raw = cfg.get("postprocess_root")
        if isinstance(root_raw, str) and root_raw:
            output_root = Path(root_raw)
            output_removed = await asyncio.to_thread(
                _wipe_directory_contents, output_root, excluded
            )
            self._live.record(job_id, f"removed {output_removed} entries under {output_root}")
        if self._should_cancel():
            raise MaintenanceCancelled(
                {
                    "targets": len(targets),
                    "deleted_downloads": deleted_downloads,
                    "output_removed": output_removed,
                }
            )

        # Phase 4: re-enqueue a fresh download for each target. We keep the
        # target row so output_dir + tags + reading_direction stick — only the
        # download history is gone.
        enqueued = 0
        for summary in targets:
            if self._should_cancel():
                raise MaintenanceCancelled(
                    {
                        "targets": len(targets),
                        "deleted_downloads": deleted_downloads,
                        "output_removed": output_removed,
                        "enqueued": enqueued,
                    }
                )
            target = summary.target
            await downloads_service.insert_pending(
                self._db,
                target.url,
                target.extractor,
                output_dir=target.output_dir,
                target_id=target.id,
            )
            enqueued += 1
            self._live.increment_done(job_id)
            self._live.record(job_id, f"enqueued: {target.url}")
        if enqueued:
            self._downloads_worker.notify()

        return {
            "targets": len(targets),
            "deleted_downloads": deleted_downloads,
            "output_removed": output_removed,
            "enqueued": enqueued,
        }

    async def _build_series_overrides(self, default_direction: str) -> dict[str, SeriesMetadata]:
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
