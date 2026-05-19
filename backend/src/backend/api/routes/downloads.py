from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.api.deps import GalleryDep, LiveProgressDep, SettingsDep, StorageDep, WorkerDep
from backend.api.schemas import (
    ChapterProgress,
    DownloadCreate,
    DownloadOut,
    ProgressOut,
)
from backend.output_dirs import coerce_optional, validate_under_root
from backend.progress import chapter_progress, chapter_progress_from_completed

router = APIRouter(tags=["downloads"])


async def _name_for(storage, target_id: int | None) -> str | None:
    if target_id is None:
        return None
    names = await storage.list_target_names([target_id])
    return names.get(target_id)


@router.post("/downloads", operation_id="createDownload")
async def create_download(
    body: DownloadCreate,
    storage: StorageDep,
    worker: WorkerDep,
    gallery: GalleryDep,
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
        cfg = await storage.get_app_config()
        root_raw = cfg.get("postprocess_root")
        if not isinstance(root_raw, str) or not root_raw:
            raise HTTPException(
                status_code=400,
                detail="output_dir requires postprocess_root to be configured",
            )
        resolved = validate_under_root(output_dir, Path(root_raw), field="output_dir")
        output_dir_str = str(resolved)
        await storage.remember_output_dir(output_dir_str)

    target = await storage.upsert_target(url, category, output_dir_str)
    download = await storage.insert_pending(
        url, category, output_dir=output_dir_str, target_id=target.id
    )
    worker.notify()
    return DownloadOut.from_download(download, name=target.name)


@router.get("/downloads", operation_id="listDownloads")
async def list_downloads(storage: StorageDep) -> list[DownloadOut]:
    rows = await storage.list_recent(50)
    ids = [d.target_id for d in rows if d.target_id is not None]
    names = await storage.list_target_names(ids)
    return [DownloadOut.from_download(d, name=names.get(d.target_id or -1)) for d in rows]


@router.get("/downloads/{download_id}", operation_id="getDownload")
async def get_download(download_id: int, storage: StorageDep) -> DownloadOut:
    d = await storage.get(download_id)
    if d is None:
        raise HTTPException(status_code=404, detail="download not found")
    return DownloadOut.from_download(d, name=await _name_for(storage, d.target_id))


@router.post("/downloads/{download_id}/cancel", operation_id="cancelDownload")
async def cancel_download(download_id: int, storage: StorageDep, worker: WorkerDep) -> DownloadOut:
    download = await storage.get(download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="download not found")
    if download.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail=f"download already in terminal state: {download.status}",
        )
    # Best-effort: tell the worker so an in-flight job unwinds on its next
    # file callback. Independently flip a still-pending row directly.
    worker.request_cancel(download_id)
    await storage.cancel_pending(download_id)
    refreshed = await storage.get(download_id)
    assert refreshed is not None
    return DownloadOut.from_download(refreshed, name=await _name_for(storage, refreshed.target_id))


@router.post("/downloads/{download_id}/requeue", operation_id="requeueDownload")
async def requeue_download(download_id: int, storage: StorageDep, worker: WorkerDep) -> DownloadOut:
    download = await storage.get(download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="download not found")
    if download.status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail=f"can only requeue terminal jobs (current: {download.status})",
        )
    if not await storage.reset_to_pending(download_id):
        raise HTTPException(status_code=409, detail="download is no longer terminal")
    worker.notify()
    refreshed = await storage.get(download_id)
    assert refreshed is not None
    return DownloadOut.from_download(refreshed, name=await _name_for(storage, refreshed.target_id))


@router.get("/downloads/{download_id}/progress", operation_id="getDownloadProgress")
async def get_progress(
    download_id: int,
    storage: StorageDep,
    settings: SettingsDep,
    live: LiveProgressDep,
) -> ProgressOut:
    download = await storage.get(download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="download not found")

    manifest = await storage.get_manifest(download_id)
    completed = live.snapshot(download_id)
    if completed is not None:
        chapters = chapter_progress_from_completed(manifest, completed)
    else:
        chapters = chapter_progress(manifest, settings.downloads_dir)
    files_present = sum(c.files_present for c in chapters)

    return ProgressOut(
        status=download.status,
        files_expected=download.files_expected,
        files_present=files_present,
        chapters=[
            ChapterProgress(name=c.name, files_total=c.files_total, files_present=c.files_present)
            for c in chapters
        ],
    )
