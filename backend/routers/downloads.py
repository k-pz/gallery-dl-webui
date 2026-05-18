from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from gallery_runtime import find_extractor
from log_hub import LogHub
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
            error=d.error,
        )


def _storage(request: Request) -> Storage:
    return request.app.state.storage


def _worker(request: Request) -> Worker:
    return request.app.state.worker


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


@router.websocket("/downloads/{download_id}/logs")
async def stream_logs(ws: WebSocket, download_id: int) -> None:
    storage: Storage = ws.app.state.storage
    hub: LogHub = ws.app.state.hub

    download = await storage.get(download_id)
    if download is None:
        await ws.close(code=4404)
        return

    await ws.accept()
    queue = hub.subscribe(download_id)
    try:
        if download.status in ("completed", "failed"):
            await ws.send_text(f"[job already finished with status: {download.status}]")
            return
        while True:
            msg = await queue.get()
            if msg is LogHub.SENTINEL:
                break
            assert isinstance(msg, str)
            await ws.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(download_id, queue)
        try:
            await ws.close()
        except Exception:
            pass
