from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app_config import service as app_config_service
from backend.app_config.constants import READING_DIRECTIONS
from backend.app_config.exceptions import PostprocessRootNotConfigured
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
from backend.downloads.postprocess import normalize_tags
from backend.downloads.progress import chapter_progress, chapter_progress_from_completed
from backend.downloads.schemas import (
    ChapterProgress,
    DownloadCreate,
    DownloadOut,
    ProgressOut,
)
from backend.events import Event, downloads_event
from backend.output_dirs.utils import coerce_optional, validate_under_root
from backend.targets import service as targets_service

router = APIRouter(tags=["downloads"])


async def _name_for(db, target_id: int | None) -> str | None:
    if target_id is None:
        return None
    names = await targets_service.list_names(db, [target_id])
    return names.get(target_id)


async def _refresh_view(db, download_id: int) -> DownloadOut:
    """Reload a row we just mutated and return the DTO. 500 if it vanished."""
    d = await service.get(db, download_id)
    if d is None:
        raise DownloadVanished(download_id)
    return DownloadOut.from_download(d, name=await _name_for(db, d.target_id))


@router.post("/downloads", operation_id="createDownload")
async def create_download(
    body: DownloadCreate,
    db: DbDep,
    worker: WorkerDep,
    gallery: GalleryDep,
    bus: EventBusDep,
) -> DownloadOut:
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    category = gallery.find_extractor(url)
    if category is None:
        raise HTTPException(
            status_code=400,
            detail="unsupported URL (no gallery-dl extractor matched)",
        )

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
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"invalid reading_direction: {body.reading_direction!r}; "
                        f"expected one of {sorted(READING_DIRECTIONS)}"
                    ),
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
    worker.notify()
    bus.publish(downloads_event("created", id=download.id))
    bus.publish(Event(topic="targets", type="updated", data={"id": target.id}))
    return DownloadOut.from_download(download, name=target.name)


@router.get("/downloads", operation_id="listDownloads")
async def list_downloads(db: DbDep) -> list[DownloadOut]:
    rows = await service.list_recent(db, 50)
    ids = [d.target_id for d in rows if d.target_id is not None]
    names = await targets_service.list_names(db, ids)
    return [DownloadOut.from_download(d, name=names.get(d.target_id or -1)) for d in rows]


@router.get("/downloads/{download_id}", operation_id="getDownload")
async def get_download(download: DownloadDep, db: DbDep) -> DownloadOut:
    return DownloadOut.from_download(download, name=await _name_for(db, download.target_id))


@router.post("/downloads/{download_id}/cancel", operation_id="cancelDownload")
async def cancel_download(
    download: DownloadDep, db: DbDep, worker: WorkerDep, bus: EventBusDep
) -> DownloadOut:
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
) -> DownloadOut:
    if download.status not in TERMINAL_STATUSES:
        raise DownloadNotTerminal(download.status)
    if not await service.reset_to_pending(db, download.id):
        raise HTTPException(status_code=409, detail="download is no longer terminal")
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
    files_present = sum(c.files_present for c in chapters)

    return ProgressOut(
        status=download.status,
        files_expected=download.files_expected,
        files_present=files_present,
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
