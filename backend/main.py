from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import gallery_runtime
from log_hub import LogHub, attach_handler
from routers import downloads, health
from settings import load_settings
from storage import Storage
from worker import Worker

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    storage = await Storage.open(settings.jobs_db_path)
    gallery_runtime.configure(settings)

    hub = LogHub()
    hub.start()
    handler = attach_handler(hub)

    worker = Worker(storage, hub, settings)
    worker.start()

    app.state.settings = settings
    app.state.storage = storage
    app.state.hub = hub
    app.state.worker = worker

    try:
        yield
    finally:
        await worker.stop()
        logging.getLogger().removeHandler(handler)
        await storage.close()


app = FastAPI(title="gallery-dl-webui", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(downloads.router, prefix="/api")

if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
