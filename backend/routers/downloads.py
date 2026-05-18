from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gallery_runtime import find_extractor
from settings import Settings
from storage import Download, Storage
from worker import Worker

router = APIRouter(tags=["downloads"])
logger = logging.getLogger(__name__)


class DownloadCreate(BaseModel):
    url: str


class DownloadOut(BaseModel):
    id: int
    url: str
    extractor: str | None
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    files_downloaded: int
    files_expected: int | None
    error: str | None

    @classmethod
    def from_download(cls, d: Download) -> DownloadOut:
        return cls(
            id=d.id,
            url=d.url,
            extractor=d.extractor,
            status=d.status,
            created_at=d.created_at,
            started_at=d.started_at,
            finished_at=d.finished_at,
            exit_code=d.exit_code,
            files_downloaded=d.files_downloaded,
            files_expected=d.files_expected,
            error=d.error,
        )


class ChapterProgress(BaseModel):
    name: str
    files_total: int
    files_present: int


class ProgressOut(BaseModel):
    status: str
    files_expected: int | None
    files_present: int
    chapters: list[ChapterProgress]


def _storage(request: Request) -> Storage:
    return request.app.state.storage


def _worker(request: Request) -> Worker:
    return request.app.state.worker


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/downloads", operation_id="createDownload")
async def create_download(body: DownloadCreate, request: Request) -> DownloadOut:
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    category = find_extractor(url)
    if category is None:
        raise HTTPException(
            status_code=400,
            detail="unsupported URL (no gallery-dl extractor matched)",
        )
    download = await _storage(request).insert_pending(url, category)
    _worker(request).notify()
    return DownloadOut.from_download(download)


@router.get("/downloads", operation_id="listDownloads")
async def list_downloads(request: Request) -> list[DownloadOut]:
    rows = await _storage(request).list_recent(50)
    return [DownloadOut.from_download(d) for d in rows]


@router.get("/downloads/{download_id}", operation_id="getDownload")
async def get_download(download_id: int, request: Request) -> DownloadOut:
    d = await _storage(request).get(download_id)
    if d is None:
        raise HTTPException(status_code=404, detail="download not found")
    return DownloadOut.from_download(d)


@router.get("/downloads/{download_id}/progress", operation_id="getDownloadProgress")
async def get_progress(download_id: int, request: Request) -> ProgressOut:
    storage = _storage(request)
    download = await storage.get(download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="download not found")

    manifest = await storage.get_manifest(download_id)
    base = _settings(request).downloads_dir

    # Group expected files by parent directory, keeping stems only. Stems are
    # used (not full filenames) because SimulationJob may predict a different
    # extension than the actual download writes.
    groups: OrderedDict[Path, list[str]] = OrderedDict()
    for rel in manifest:
        p = Path(rel)
        groups.setdefault(p.parent, []).append(p.stem)

    chapters: list[ChapterProgress] = []
    total_present = 0
    for parent, expected_stems in groups.items():
        directory = base / parent
        try:
            present_stems = {child.stem for child in directory.iterdir() if child.is_file()}
        except FileNotFoundError:
            present_stems = set()
        present = sum(1 for s in expected_stems if s in present_stems)
        total_present += present
        name = parent.name if str(parent) != "." else ""
        chapters.append(
            ChapterProgress(name=name, files_total=len(expected_stems), files_present=present)
        )

    return ProgressOut(
        status=download.status,
        files_expected=download.files_expected,
        files_present=total_present,
        chapters=chapters,
    )
