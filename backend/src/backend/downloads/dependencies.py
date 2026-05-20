from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from backend.dependencies import DbDep
from backend.downloads import service
from backend.downloads.exceptions import DownloadNotFound
from backend.downloads.gallery import Gallery
from backend.downloads.live_progress import LiveProgress
from backend.downloads.models import Download

if TYPE_CHECKING:
    from backend.downloads.worker import Worker


def get_worker(request: Request) -> Worker:
    return request.app.state.worker


def get_gallery(request: Request) -> Gallery:
    return request.app.state.gallery


def get_live_progress(request: Request) -> LiveProgress:
    return request.app.state.live_progress


async def valid_download_id(download_id: int, db: DbDep) -> Download:
    download = await service.get(db, download_id)
    if download is None:
        raise DownloadNotFound()
    return download


WorkerDep = Annotated["Worker", Depends(get_worker)]
GalleryDep = Annotated[Gallery, Depends(get_gallery)]
LiveProgressDep = Annotated[LiveProgress, Depends(get_live_progress)]
DownloadDep = Annotated[Download, Depends(valid_download_id)]
