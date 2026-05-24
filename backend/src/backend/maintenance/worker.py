from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

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
from backend.events import EventBus, maintenance_event, maintenance_progress_event, targets_event
from backend.maintenance import service
from backend.maintenance.komga import (
    KomgaPushResult,
    TargetForPush,
    push_series_statuses,
    validate_credentials,
)
from backend.maintenance.live_progress import MaintenanceLiveProgress
from backend.targets import service as targets_service

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.downloads.gallery import Gallery
    from backend.downloads.worker import Worker

logger = logging.getLogger(__name__)

# Filename of the trigger file the webapp drops into DATA_DIR to ask the
# host-side `gallery-dl-webui-update.path` unit to fire its
# `gallery-dl-webui-update.service`. The update service removes the file in
# ExecStartPre so a future write re-arms the trigger.
UPDATE_TRIGGER_FILENAME = ".update-request"
UPDATE_PATH_UNIT = "gallery-dl-webui-update.path"


def _exclude_dirs(cfg: dict[str, object]) -> list[str]:
    """Pull the user-configured directory-name exclusions out of app_config."""
    raw = cfg.get("postprocess_excluded_dir_names")
    if not isinstance(raw, list):
        return []
    return [name for name in raw if isinstance(name, str) and name]


async def _designated_output_dirs(db: aiosqlite.Connection, cfg: dict[str, object]) -> list[Path]:
    """The set of output dirs targets actually write into.

    Maintenance is intentionally scoped to these dirs (not the whole
    `postprocess_root`) so unrelated directories that happen to sit under
    root — user photo folders, exports, anything the app didn't put there —
    are never touched. Each target's `output_dir` wins; targets without one
    fall back to `postprocess_default_output_dir` when set, matching how the
    downloads worker resolves a job's output_dir at pack time.
    """
    default_raw = cfg.get("postprocess_default_output_dir")
    default = default_raw if isinstance(default_raw, str) and default_raw else None
    targets = await targets_service.list_all(db)
    # Dedupe by the string form so two targets sharing one output dir collapse
    # to a single walk. We preserve the first-seen path object (rather than
    # round-tripping through `.resolve()`) so symlinks in the configured path
    # are kept verbatim — the user's exclusion rules are name-based.
    seen: dict[str, Path] = {}
    for summary in targets:
        raw = summary.output_dir or default
        if not raw:
            continue
        if raw in seen:
            continue
        seen[raw] = Path(raw)
    return list(seen.values())


def _write_update_trigger(path: Path) -> None:
    """Create or refresh the systemd path-unit trigger file.

    The update.service's ExecStartPre removes the file before each run, so a
    plain write is enough to fire the path unit. Overwriting an existing
    file (e.g. a stale trigger left behind when the path unit was disabled)
    is fine — the next time the unit is enabled, PathExists fires again.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("requested\n", encoding="utf-8")


def _update_path_unit_enabled() -> bool:
    """Best-effort check: is gallery-dl-webui-update.path enabled?

    `systemctl is-enabled` exits 0 only for enabled units, non-zero otherwise
    (disabled, masked, not-found, no systemd available). Any failure mode is
    treated as "not ready", which matches what users actually want: a clear
    error instead of a silent no-op when the host-side units are missing.
    """
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return False
    try:
        result = subprocess.run(
            [systemctl, "is-enabled", UPDATE_PATH_UNIT],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


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
    """Adapter that funnels rename_packed_chapters callbacks into the live store
    and also fan-outs to the event bus so websocket clients can tail progress
    without polling. The worker thread invokes `total` and `step`; both end up
    publishing through `EventBus.publish_threadsafe` to bounce back to the
    asyncio loop.
    """

    def __init__(
        self,
        live: MaintenanceLiveProgress,
        job_id: int,
        bus: EventBus | None,
        loop: asyncio.AbstractEventLoop | None,
    ) -> None:
        self._live = live
        self._job_id = job_id
        self._bus = bus
        self._loop = loop

    def total(self, n: int) -> None:
        self._live.set_total(self._job_id, n)
        line = f"scanning… found {n} archive(s)"
        self._live.record(self._job_id, line)
        self._publish(total=n, line=line)

    def step(self, line: str) -> None:
        self._live.increment_done(self._job_id)
        self._live.record(self._job_id, line)
        self._publish(line=line)

    def _publish(self, **data) -> None:
        if self._bus is None or self._loop is None:
            return
        self._bus.publish_threadsafe(self._loop, maintenance_progress_event(self._job_id, **data))


class MaintenanceWorker:
    def __init__(
        self,
        db: aiosqlite.Connection,
        live: MaintenanceLiveProgress,
        *,
        settings: Settings | None = None,
        downloads_worker: Worker | None = None,
        gallery: Gallery | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._db = db
        self._live = live
        # Optional because the rebuild kind is the only one that needs to
        # touch disk + the downloads queue; the rename/regen kinds work with
        # just the db. Tests can therefore still construct the worker bare.
        # `gallery` is consulted by the regen kind to rediscover series
        # status / tags / chapter dates from upstream; without it, regen
        # falls back to whatever's already on the target row.
        self._settings = settings
        self._downloads_worker = downloads_worker
        self._gallery = gallery
        self._bus = event_bus
        self._loop: asyncio.AbstractEventLoop | None = None
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
        # Per-job credentials for kinds that need them (only push_komga_series_status
        # today). Stashed by the router before the DB row is created so the
        # worker can claim → execute → drop without ever persisting secrets.
        # Bounded by the number of pending+running jobs; cleared on terminal
        # transitions and on cancel-pending.
        self._pending_params: dict[int, dict[str, object]] = {}

    def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._task = asyncio.create_task(self._run(), name="maintenance-worker")

    def _emit(self, action: str, **data) -> None:
        if self._bus is not None:
            self._bus.publish(maintenance_event(action, **data))

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

    def stash_params(self, id_: int, params: dict[str, object]) -> None:
        """Register per-job parameters (e.g. Komga credentials) by job id."""
        self._pending_params[id_] = params

    def drop_params(self, id_: int) -> None:
        """Discard stashed params (called when a pending job is cancelled before claim)."""
        self._pending_params.pop(id_, None)

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
            self._emit("updated", id=job.id, status="running")
            try:
                result = await self._execute(job.kind, job.id)
            except MaintenanceCancelled as cancelled:
                logger.info("maintenance job %d cancelled", job.id)
                self._live.record(job.id, f"cancelled: {cancelled.partial}")
                await service.mark_cancelled(self._db, job.id, cancelled.partial)
                self._live.clear(job.id)
                self._current_id = None
                self._cancel_requested = False
                self._pending_params.pop(job.id, None)
                self._emit("updated", id=job.id, status="cancelled")
                continue
            except Exception as exc:
                logger.exception("maintenance job %d failed", job.id)
                self._live.record(job.id, f"failed: {exc!r}")
                await service.mark_failed(self._db, job.id, repr(exc))
                self._live.clear(job.id)
                self._current_id = None
                self._cancel_requested = False
                self._pending_params.pop(job.id, None)
                self._emit("updated", id=job.id, status="failed")
                continue
            self._live.record(job.id, f"done: {result}")
            await service.mark_completed(self._db, job.id, result)
            self._live.clear(job.id)
            self._current_id = None
            self._cancel_requested = False
            self._pending_params.pop(job.id, None)
            self._emit("updated", id=job.id, status="completed")

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    _RUNNERS: ClassVar[dict[str, str]] = {
        "rename_chapters": "_run_rename",
        "regenerate_series_metadata": "_run_regenerate_metadata",
        "rebuild_library": "_run_rebuild_library",
        "push_komga_series_status": "_run_push_komga_status",
        "update_lxc": "_run_update_lxc",
        "unwatch_ended_series": "_run_unwatch_ended_series",
    }

    async def _execute(self, kind: str, job_id: int) -> dict[str, Any]:
        method_name = self._RUNNERS.get(kind)
        if method_name is None:
            raise ValueError(f"unsupported maintenance kind: {kind}")
        return await getattr(self, method_name)(job_id)

    async def _run_rename(self, job_id: int) -> dict[str, int]:
        cfg = await app_config_service.get_all(self._db)
        root_str = cfg.get("postprocess_root")
        if not isinstance(root_str, str) or not root_str:
            raise ValueError("postprocess_root is not configured")
        template = cfg.get("chapter_naming_template")
        if not isinstance(template, str) or not template:
            template = DEFAULT_CHAPTER_NAMING_TEMPLATE
        sink = _JobProgressSink(self._live, job_id, self._bus, self._loop)
        exclude_dirs = _exclude_dirs(cfg)
        output_roots = await _designated_output_dirs(self._db, cfg)
        result = await asyncio.to_thread(
            postprocess.rename_packed_chapters,
            output_roots,
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
        sink = _JobProgressSink(self._live, job_id, self._bus, self._loop)

        # Rediscovery pass first: hit each target's URL with a metadata-only
        # sim so series_status / tags get filled (fill-only) and chapter
        # dates are surfaced for the regen below. Without a Gallery wired in
        # we skip this and fall back to whatever's already on the targets.
        chapter_dates_by_series = await self._rediscover_series_metadata(job_id, sink)

        overrides_by_series = await self._build_series_overrides(default_direction)

        def lookup(series_name: str) -> SeriesMetadata | None:
            return overrides_by_series.get(sanitize(series_name).lower())

        def date_for(series_name: str, chapter: str) -> str | None:
            key = sanitize(series_name).lower()
            return chapter_dates_by_series.get(key, {}).get(chapter)

        exclude_dirs = _exclude_dirs(cfg)
        output_roots = await _designated_output_dirs(self._db, cfg)
        result = await asyncio.to_thread(
            postprocess.regenerate_series_metadata,
            output_roots,
            lookup,
            sink,
            self._should_cancel,
            exclude_dirs,
            date_for if chapter_dates_by_series else None,
        )
        return asdict(result)

    async def _rediscover_series_metadata(
        self, job_id: int, sink: _JobProgressSink
    ) -> dict[str, dict[str, str]]:
        """Run a metadata-only sim per target. Returns chapter-date lookup keyed
        by sanitised series name -> chapter -> ISO date.

        Side effects: each target gets its `series_status` / `tags` columns
        filled (fill-only via `set_series_*`), so subsequent regens (and the
        `_build_series_overrides` call below this one) see the refreshed data.
        Best-effort: errors on individual targets are logged and the
        rediscovery continues with the next target.
        """
        if self._gallery is None:
            return {}
        targets = await targets_service.list_all(self._db)
        out: dict[str, dict[str, str]] = {}
        if not targets:
            return out
        sink.step(f"rediscovering metadata for {len(targets)} target(s)…")
        for target in targets:
            if self._should_cancel():
                # Rediscovery is best-effort; cancellation aborts the loop and
                # the regen still runs on whatever was rediscovered so far.
                break
            if not target.url:
                continue
            try:
                meta = await asyncio.to_thread(self._gallery.extract_metadata, target.url)
            except Exception as exc:
                logger.exception("rediscover failed for target %s", target.url)
                sink.step(f"rediscover failed: {target.url}: {exc!r}")
                continue
            if meta.series_status:
                await targets_service.set_series_status(self._db, target.id, meta.series_status)
            if meta.series_tags:
                await targets_service.set_series_tags(self._db, target.id, meta.series_tags)
            if meta.chapter_dates:
                # Index by sanitised series name so the regen lookup can
                # match against the ComicInfo.xml `Series` field — same
                # pattern `_build_series_overrides` uses.
                for (manga, chapter), date in meta.chapter_dates.items():
                    key = sanitize(manga).lower()
                    out.setdefault(key, {})[chapter] = date
            sink.step(f"rediscovered: {target.url}")
        return out

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

        sink = _JobProgressSink(self._live, job_id, self._bus, self._loop)
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

        # Phase 3: wipe each designated output dir (the ones targets actually
        # write into). Scoping to these dirs — not the whole postprocess_root —
        # means unrelated content sitting next to them under root is left
        # untouched. Excluded names (NAS trash etc.) survive the wipe so we
        # don't tank a `#recycle` bin somebody actually cares about. With no
        # designated dirs (no targets configured, no default), there's nothing
        # to wipe and the phase no-ops silently.
        output_removed = 0
        output_roots = await _designated_output_dirs(self._db, cfg)
        for output_dir in output_roots:
            removed = await asyncio.to_thread(_wipe_directory_contents, output_dir, excluded)
            output_removed += removed
            self._live.record(job_id, f"removed {removed} entries under {output_dir}")
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
        for target in targets:
            if self._should_cancel():
                raise MaintenanceCancelled(
                    {
                        "targets": len(targets),
                        "deleted_downloads": deleted_downloads,
                        "output_removed": output_removed,
                        "enqueued": enqueued,
                    }
                )
            await downloads_service.insert_pending(
                self._db,
                target.url,
                target.extractor,
                output_dir=target.output_dir,
                target_id=target.id,
            )
            # Same rationale as create_download: queuing here counts as a
            # poll so the periodic poller doesn't re-queue the moment the
            # rebuild's download finishes.
            await targets_service.mark_polled(self._db, target.id)
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

    async def _run_push_komga_status(self, job_id: int) -> dict[str, int]:
        """Push every target's local `series_status` into the matching Komga series.

        Credentials come from `_pending_params` (router-stashed at schedule
        time); we pop them up front so a retry would correctly fail rather
        than silently re-using stale values. Series with no local status or a
        local status that doesn't map to a Komga enum are skipped; same for
        zero/multiple Komga matches by name. The job itself never fails on
        per-series errors — it tallies them and reports the breakdown.
        """
        params = self._pending_params.pop(job_id, None)
        creds = validate_credentials(params)

        targets = await targets_service.list_all(self._db)
        # Only push for targets that have a name to search by. Status-less
        # targets are still counted (and skipped with a clear log line) so the
        # totals make sense.
        candidates: list[TargetForPush] = [
            TargetForPush(name=t.name, series_status=t.series_status or "")
            for t in targets
            if t.name
        ]

        sink = _JobProgressSink(self._live, job_id, self._bus, self._loop)

        async def _on_cancel(partial: KomgaPushResult) -> None:
            raise MaintenanceCancelled(partial.as_dict())

        result = await push_series_statuses(
            creds,
            candidates,
            on_total=sink.total,
            on_step=sink.step,
            should_cancel=self._should_cancel,
            on_cancel=_on_cancel,
        )
        return result.as_dict()

    async def _run_unwatch_ended_series(self, job_id: int) -> dict[str, int]:
        """Flip every watched target whose series_status is "Ended" to unwatched.

        Bulk DB update so the run is O(1) trips regardless of library size; the
        per-target events are emitted afterwards from the returned id list so
        connected UI clients refresh without polling. Cancellation isn't
        plumbed in because the single UPDATE is effectively atomic — there's
        no progress-loop checkpoint to honour a mid-run signal at.
        """
        sink = _JobProgressSink(self._live, job_id, self._bus, self._loop)
        ids = await targets_service.unwatch_ended(self._db)
        sink.total(len(ids))
        for target_id in ids:
            sink.step(f"unwatched target {target_id}")
            if self._bus is not None:
                self._bus.publish(targets_event("updated", id=target_id))
        return {"unwatched": len(ids)}

    async def _run_update_lxc(self, job_id: int) -> dict[str, str]:
        """Kick off an in-place LXC update by dropping a trigger file in DATA_DIR.

        Privilege bridge: the sandboxed webapp cannot run the host-side
        `/usr/local/bin/update` (needs root + writes outside ReadWritePaths).
        Instead a pre-installed systemd `gallery-dl-webui-update.path` unit
        watches `${DATA_DIR}/.update-request`; writing the file fires the
        corresponding `gallery-dl-webui-update.service` (root, oneshot), which
        runs the updater and restarts the webapp at the end.

        The maintenance job completes the moment the trigger is written — the
        actual update takes minutes and ends in the webapp being killed, so
        there's no waitable terminal state from inside this process. The UI
        explains the rest.
        """
        if self._settings is None:
            raise ValueError("update_lxc requires settings")
        sink = _JobProgressSink(self._live, job_id, self._bus, self._loop)

        # Pre-check: refuse to leave a useless trigger file if the path unit
        # isn't installed (older CTs that pre-date this feature). Surfacing the
        # mismatch here keeps the UI from claiming "done" when nothing
        # actually fires. `systemctl is-enabled` returns 0 only for enabled
        # units; on hosts without systemd it errors out and we skip too.
        if not await asyncio.to_thread(_update_path_unit_enabled):
            raise ValueError(
                "update infrastructure not installed: enable "
                f"{UPDATE_PATH_UNIT} (run /usr/local/bin/update once from the "
                "LXC console to install it)"
            )

        trigger = self._settings.data_dir / UPDATE_TRIGGER_FILENAME
        sink.step(f"writing update trigger: {trigger}")
        await asyncio.to_thread(_write_update_trigger, trigger)
        sink.step("trigger written — systemd will run /usr/local/bin/update")
        sink.step(
            "the webapp will be restarted at the end of the update; "
            "reload this page once it comes back"
        )
        return {"status": "kicked_off", "trigger": str(trigger)}

    async def _build_series_overrides(self, default_direction: str) -> dict[str, SeriesMetadata]:
        """Index targets by sanitized series name so the regen pass can map
        CBZ-on-disk back to the user's tags + reading direction + series status."""
        targets = await targets_service.list_all(self._db)
        result: dict[str, SeriesMetadata] = {}
        for target in targets:
            if not target.name:
                continue
            key = sanitize(target.name).lower()
            result[key] = SeriesMetadata(
                name=target.name,
                tags=normalize_tags(list(target.tags)),
                reading_direction=normalize_reading_direction(
                    target.reading_direction or default_direction
                ),
                status=target.series_status or "",
            )
        return result
