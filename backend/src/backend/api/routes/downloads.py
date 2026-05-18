from fastapi import APIRouter, HTTPException

from backend.api.deps import GalleryDep, LiveProgressDep, SettingsDep, StorageDep, WorkerDep
from backend.api.schemas import (
    ChapterProgress,
    DownloadCreate,
    DownloadOut,
    ProgressOut,
)
from backend.progress import chapter_progress, chapter_progress_from_completed

router = APIRouter(tags=["downloads"])


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
    download = await storage.insert_pending(url, category)
    worker.notify()
    return DownloadOut.from_download(download)


@router.get("/downloads", operation_id="listDownloads")
async def list_downloads(storage: StorageDep) -> list[DownloadOut]:
    rows = await storage.list_recent(50)
    return [DownloadOut.from_download(d) for d in rows]


@router.get("/downloads/{download_id}", operation_id="getDownload")
async def get_download(download_id: int, storage: StorageDep) -> DownloadOut:
    d = await storage.get(download_id)
    if d is None:
        raise HTTPException(status_code=404, detail="download not found")
    return DownloadOut.from_download(d)


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
