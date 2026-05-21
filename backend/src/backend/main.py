import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app_config.router import router as config_router
from backend.config import REPO_ROOT, Settings, load_settings
from backend.database import open_database
from backend.downloads import service as downloads_service
from backend.downloads.gallery import Gallery
from backend.downloads.live_progress import LiveProgress
from backend.downloads.router import router as downloads_router
from backend.downloads.worker import Worker
from backend.events import EventBus
from backend.health.router import router as health_router
from backend.library.router import router as library_router
from backend.logging_setup import configure_logging
from backend.logs.router import router as logs_router
from backend.maintenance import service as maintenance_service
from backend.maintenance.live_progress import MaintenanceLiveProgress
from backend.maintenance.router import router as maintenance_router
from backend.maintenance.worker import MaintenanceWorker
from backend.output_dirs.router import router as output_dirs_router
from backend.realtime.router import router as realtime_router
from backend.targets.poller import Poller
from backend.targets.router import router as targets_router

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
    settings = settings_factory()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        level = configure_logging()
        logger.info("logging configured at level %s", logging.getLevelName(level))

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.downloads_dir.mkdir(parents=True, exist_ok=True)

        db = await open_database(settings.jobs_db_path)
        gallery = gallery_factory(settings)
        event_bus = EventBus()
        # Shared lock that serialises multi-statement DB sequences across the
        # downloads worker pool, the maintenance worker, and the poller. We
        # use one aiosqlite connection app-wide; an unclosed cursor from one
        # coroutine otherwise blocks a `commit()` from another. The lock is
        # held briefly — only for claim transactions and terminal updates —
        # so request handlers remain responsive.
        db_lock = asyncio.Lock()

        interrupted = await downloads_service.mark_interrupted_on_boot(db)
        if interrupted:
            logger.warning("marked %d in-flight job(s) as failed on boot", interrupted)

        interrupted_maint = await maintenance_service.mark_interrupted_on_boot(db)
        if interrupted_maint:
            logger.warning(
                "marked %d in-flight maintenance job(s) as failed on boot",
                interrupted_maint,
            )

        live_progress = LiveProgress()
        worker = Worker(db, gallery, live_progress, event_bus=event_bus, db_lock=db_lock)
        worker.start()
        maintenance_live = MaintenanceLiveProgress()
        maintenance_worker = MaintenanceWorker(
            db,
            maintenance_live,
            settings=settings,
            downloads_worker=worker,
            gallery=gallery,
            event_bus=event_bus,
            db_lock=db_lock,
        )
        maintenance_worker.start()
        poller = Poller(db, worker, event_bus=event_bus, db_lock=db_lock)
        poller.start()

        app.state.settings = settings
        app.state.db = db
        app.state.gallery = gallery
        app.state.worker = worker
        app.state.live_progress = live_progress
        app.state.poller = poller
        app.state.maintenance_worker = maintenance_worker
        app.state.maintenance_live = maintenance_live
        app.state.event_bus = event_bus
        app.state.db_lock = db_lock

        try:
            yield
        finally:
            await poller.stop()
            await maintenance_worker.stop()
            await worker.stop()
            await db.close()

    app = FastAPI(title="gallery-dl-webui", lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
    app.include_router(downloads_router, prefix="/api")
    app.include_router(targets_router, prefix="/api")
    app.include_router(output_dirs_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(library_router, prefix="/api")
    app.include_router(maintenance_router, prefix="/api")
    app.include_router(realtime_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")

    cors_origins = list(settings.cors_origins)
    # In dev mode the Vite proxy origin needs CORS; in prod the SPA is
    # same-origin and only env-configured origins (e.g. a browser extension)
    # need it.
    if not (serve_frontend and FRONTEND_DIST.is_dir()):
        cors_origins.append("http://localhost:5173")
    if cors_origins or settings.cors_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_origin_regex=settings.cors_origin_regex,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    if serve_frontend and FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            candidate = FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
