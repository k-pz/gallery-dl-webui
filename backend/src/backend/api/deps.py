from typing import Annotated

from fastapi import Depends, Request

from backend.gallery import Gallery
from backend.live_progress import LiveProgress
from backend.poller import Poller
from backend.settings import Settings
from backend.storage import Storage
from backend.worker import Worker


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_worker(request: Request) -> Worker:
    return request.app.state.worker


def get_gallery(request: Request) -> Gallery:
    return request.app.state.gallery


def get_live_progress(request: Request) -> LiveProgress:
    return request.app.state.live_progress


def get_poller(request: Request) -> Poller:
    return request.app.state.poller


SettingsDep = Annotated[Settings, Depends(get_settings)]
StorageDep = Annotated[Storage, Depends(get_storage)]
WorkerDep = Annotated[Worker, Depends(get_worker)]
GalleryDep = Annotated[Gallery, Depends(get_gallery)]
LiveProgressDep = Annotated[LiveProgress, Depends(get_live_progress)]
PollerDep = Annotated[Poller, Depends(get_poller)]
