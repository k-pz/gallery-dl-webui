import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import downloads, health
from backend.gallery import Gallery
from backend.live_progress import LiveProgress
from backend.settings import REPO_ROOT, Settings, load_settings
from backend.storage import Storage
from backend.worker import Worker

logger = logging.getLogger(__name__)

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

GalleryFactory = Callable[[Settings], Gallery]
SettingsFactory = Callable[[], Settings]


def create_app(
    *,
    settings_factory: SettingsFactory = load_settings,
    gallery_factory: GalleryFactory = Gallery,
    serve_frontend: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = settings_factory()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.downloads_dir.mkdir(parents=True, exist_ok=True)

        storage = await Storage.open(settings.jobs_db_path)
        gallery = gallery_factory(settings)

        interrupted = await storage.mark_interrupted_on_boot()
        if interrupted:
            logger.warning("marked %d in-flight job(s) as failed on boot", interrupted)

        live_progress = LiveProgress()
        worker = Worker(storage, gallery, live_progress)
        worker.start()

        app.state.settings = settings
        app.state.storage = storage
        app.state.gallery = gallery
        app.state.worker = worker
        app.state.live_progress = live_progress

        try:
            yield
        finally:
            await worker.stop()
            await storage.close()

    app = FastAPI(title="gallery-dl-webui", lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    app.include_router(downloads.router, prefix="/api")

    if serve_frontend and FRONTEND_DIST.is_dir():
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

    return app


app = create_app()
