from pathlib import Path

from fastapi import APIRouter

from backend.app_config import service as app_config_service
from backend.app_config.constants import READING_DIRECTIONS
from backend.app_config.exceptions import PostprocessRootNotConfigured
from backend.comic_metadata import normalize_tags
from backend.dependencies import DbDep, EventBusDep, SettingsDep
from backend.downloads import service
from backend.downloads.constants import TERMINAL_STATUSES
from backend.downloads.dependencies import (
    DownloadDep,
    GalleryDep,
    LiveProgressDep,
    WorkerDep,
)
from backend.downloads.exceptions import (
    DownloadAlreadyTerminal,
    DownloadNotTerminal,
    DownloadVanished,
)
from backend.downloads.outcomes import ChapterOutcome
from backend.downloads.progress import chapter_progress, chapter_progress_from_completed
from backend.downloads.schemas import (
    ChapterProgress,
    Download,
    DownloadCreate,
    ProgressOut,
)
from backend.events import Event, downloads_event
from backend.exceptions import BadRequestError, ConflictError
from backend.output_dirs.utils import coerce_optional, validate_under_root
from backend.targets import service as targets_service

router = APIRouter(tags=["downloads"])


async def _refresh_view(db, download_id: int) -> Download:
    """Reload a row we just mutated. 500 if it vanished."""
    d = await service.get(db, download_id)
    if d is None:
        raise DownloadVanished(download_id)
    return d


@router.post("/downloads", operation_id="createDownload")
async def create_download(
    body: DownloadCreate,
    db: DbDep,
    worker: WorkerDep,
    gallery: GalleryDep,
    bus: EventBusDep,
) -> Download:
    url = body.url.strip()
    if not url:
        raise BadRequestError("url is required")
    category = gallery.find_extractor(url)
    if category is None:
        raise BadRequestError("unsupported URL (no gallery-dl extractor matched)")

    output_dir = coerce_optional(body.output_dir)
    output_dir_str: str | None = None
    if output_dir is not None:
        cfg = await app_config_service.get_all(db)
        root_raw = cfg.get("postprocess_root")
        if not isinstance(root_raw, str) or not root_raw:
            raise PostprocessRootNotConfigured("output_dir")
        resolved = validate_under_root(output_dir, Path(root_raw), field="output_dir")
        output_dir_str = str(resolved)
        await app_config_service.remember_output_dir(db, output_dir_str)

    tags: list[str] | None = None
    if body.tags is not None:
        tags = normalize_tags(body.tags)

    reading_direction: str | None = None
    if body.reading_direction is not None:
        cleaned = body.reading_direction.strip().lower()
        if cleaned:
            if cleaned not in READING_DIRECTIONS:
                raise BadRequestError(
                    f"invalid reading_direction: {body.reading_direction!r}; "
                    f"expected one of {sorted(READING_DIRECTIONS)}"
                )
            reading_direction = cleaned

    target = await targets_service.upsert(
        db,
        url,
        category,
        output_dir_str,
        watched=body.watched,
        tags=tags,
        reading_direction=reading_direction,
    )
    download = await service.insert_pending(
        db, url, category, output_dir=output_dir_str, target_id=target.id
    )
    # Submitting counts as a poll: without this, a freshly-watched target keeps
    # `last_polled_at = NULL` and the poller's next tick re-queues it the moment
    # this download finishes (poller.is_due treats NULL as "always due").
    await targets_service.mark_polled(db, target.id)
    worker.notify()
    bus.publish(downloads_event("created", id=download.id))
    bus.publish(Event(topic="targets", type="updated", data={"id": target.id}))
    return download


@router.get("/downloads", operation_id="listDownloads")
async def list_downloads(db: DbDep) -> list[Download]:
    return await service.list_recent(db, 50)


@router.get("/downloads/{download_id}", operation_id="getDownload")
async def get_download(download: DownloadDep) -> Download:
    return download


@router.post("/downloads/{download_id}/cancel", operation_id="cancelDownload")
async def cancel_download(
    download: DownloadDep, db: DbDep, worker: WorkerDep, bus: EventBusDep
) -> Download:
    if download.status in TERMINAL_STATUSES:
        raise DownloadAlreadyTerminal(download.status)
    # Best-effort: tell the worker so an in-flight job unwinds on its next
    # file callback. Independently flip a still-pending row directly.
    worker.request_cancel(download.id)
    await service.cancel_pending(db, download.id)
    bus.publish(downloads_event("updated", id=download.id))
    return await _refresh_view(db, download.id)


@router.post("/downloads/{download_id}/requeue", operation_id="requeueDownload")
async def requeue_download(
    download: DownloadDep, db: DbDep, worker: WorkerDep, bus: EventBusDep
) -> Download:
    if download.status not in TERMINAL_STATUSES:
        raise DownloadNotTerminal(download.status)
    if not await service.reset_to_pending(db, download.id):
        raise ConflictError("download is no longer terminal")
    worker.notify()
    bus.publish(downloads_event("updated", id=download.id, status="pending"))
    return await _refresh_view(db, download.id)


@router.get("/downloads/{download_id}/progress", operation_id="getDownloadProgress")
async def get_progress(
    download: DownloadDep,
    db: DbDep,
    settings: SettingsDep,
    live: LiveProgressDep,
) -> ProgressOut:
    if download.status in TERMINAL_STATUSES:
        outcomes = await service.get_chapter_outcomes(db, download.id)
        if any(o.status != "pending" for o in outcomes):
            return _progress_from_outcomes(download, outcomes)
        # Legacy terminal job (no persisted outcomes): keep the neutral fallback.
        manifest = await service.get_manifest(db, download.id)
        chapters = chapter_progress(
            manifest, settings.downloads_dir, download.status, download.postprocess_status
        )
        return _legacy_progress(download, chapters)

    manifest = await service.get_manifest(db, download.id)
    completed = live.snapshot(download.id)
    if completed is not None:
        chapters = chapter_progress_from_completed(
            manifest, completed, download.status, download.postprocess_status
        )
    else:
        chapters = chapter_progress(
            manifest, settings.downloads_dir, download.status, download.postprocess_status
        )
    return _legacy_progress(download, chapters)


def _legacy_progress(download: Download, chapters: list) -> ProgressOut:
    files_present = sum(c.files_present for c in chapters)
    return ProgressOut(
        status=download.status,
        files_expected=download.files_expected,
        files_present=files_present,
        chapters_discovered=download.chapters_discovered,
        chapters_needed=download.chapters_total,
        chapters=[
            ChapterProgress(
                name=c.name,
                files_total=c.files_total,
                files_present=c.files_present,
                stage=c.stage,
            )
            for c in chapters
        ],
    )


# A skipped chapter is already on disk (you have it) and a downloaded one is
# done — both are "settled" so the progress bar can complete. A failed chapter
# stays "downloading" so the bar reflects that the job didn't fully succeed.
_OUTCOME_STAGE = {
    "downloaded": "downloaded",
    "skipped": "completed",
    "failed": "downloading",
    "pending": "downloading",
}


def _chapter_files(o: ChapterOutcome) -> tuple[int, int]:
    """(files_present, files_total) for a chapter outcome. Skipped chapters are
    counted as present (already on disk); failed/pending as not-yet-present."""
    if o.status == "downloaded":
        return o.pages, max(o.pages, 1)
    if o.status == "skipped":
        return 1, 1
    return 0, max(o.pages, 1)


def _progress_from_outcomes(download: Download, outcomes: list[ChapterOutcome]) -> ProgressOut:
    counts = {"downloaded": 0, "failed": 0, "skipped": 0}
    chapters: list[ChapterProgress] = []
    files_present = 0
    for o in outcomes:
        present, total = _chapter_files(o)
        files_present += present
        if o.status in counts:
            counts[o.status] += 1
        chapters.append(
            ChapterProgress(
                name=o.name,
                files_total=total,
                files_present=present,
                stage=_OUTCOME_STAGE.get(o.status, "downloading"),
                status=o.status,
                pages=o.pages,
                title=o.title or None,
                date=o.date or None,
                error=o.error,
            )
        )
    return ProgressOut(
        status=download.status,
        files_expected=download.files_expected,
        files_present=files_present,
        chapters_discovered=download.chapters_discovered,
        chapters_needed=download.chapters_total,
        chapters_downloaded=counts["downloaded"],
        chapters_failed=counts["failed"],
        chapters_skipped=counts["skipped"],
        chapters=chapters,
    )
