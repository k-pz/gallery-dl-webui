"""Worker loops must survive transient failures in their bookkeeping tails.

A DB/OS error after a job's main work (postprocess bookkeeping, terminal
status persistence) used to propagate out of the loop coroutine, silently
killing the worker task and stalling the queue forever.
"""

from pathlib import Path

import aiosqlite
import pytest

from backend.config import Settings
from backend.downloads import service as downloads_service
from backend.downloads.live_progress import LiveProgress
from backend.downloads.worker import Worker
from backend.maintenance import service as maintenance_service
from backend.maintenance import worker as maintenance_worker_module
from backend.maintenance.live_progress import MaintenanceLiveProgress
from backend.maintenance.worker import MaintenanceWorker
from tests._helpers import wait_for
from tests.fakes import FakeGallery, FakeGalleryConfig


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data")
    s.downloads_dir.mkdir(parents=True, exist_ok=True)
    return s


async def test_downloads_worker_survives_postprocess_bookkeeping_failure(
    settings: Settings, db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exception in the post-download tail must not kill the queue."""
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["ch1/001.jpg"]
    config.manifest_for["https://example/y"] = ["ch1/001.jpg"]
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]

    # _run_postprocess's first await — raising here lands in the unprotected
    # tail of _process, after the job row has already gone terminal.
    async def boom(_db: aiosqlite.Connection) -> dict[str, object]:
        raise RuntimeError("transient db hiccup")

    monkeypatch.setattr("backend.downloads.worker.app_config_service.get_all", boom)

    worker.start()
    try:
        first = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def first_done() -> bool:
            row = await downloads_service.get(db, first.id)
            return row is not None and row.status == "completed"

        await wait_for(first_done)

        # The loop must still be alive and able to process the next job.
        second = await downloads_service.insert_pending(db, "https://example/y", "fake")
        worker.notify()

        async def second_done() -> bool:
            row = await downloads_service.get(db, second.id)
            return row is not None and row.status == "completed"

        await wait_for(second_done)
    finally:
        await worker.stop()


async def test_maintenance_worker_survives_mark_completed_failure(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure persisting the terminal state must not kill the loop."""
    real_mark_completed = maintenance_service.mark_completed
    failures = {"remaining": 1}

    async def flaky_mark_completed(*args, **kwargs):
        if failures["remaining"] > 0:
            failures["remaining"] -= 1
            raise RuntimeError("transient db hiccup")
        return await real_mark_completed(*args, **kwargs)

    monkeypatch.setattr(maintenance_worker_module.service, "mark_completed", flaky_mark_completed)

    worker = MaintenanceWorker(db, MaintenanceLiveProgress())
    worker.start()
    try:
        # unwatch_ended_series only needs the db — cheapest kind to run.
        first = await maintenance_service.create_pending(db, "unwatch_ended_series")
        worker.notify()

        async def first_settled() -> bool:
            # mark_completed blew up, so the row stays 'running' — wait until
            # the worker has moved past it (current id cleared).
            return worker._current_id is None and failures["remaining"] == 0

        await wait_for(first_settled)

        second = await maintenance_service.create_pending(db, "unwatch_ended_series")
        worker.notify()

        async def second_done() -> bool:
            row = await maintenance_service.get_job(db, second.id)
            return row is not None and row.status == "completed"

        await wait_for(second_done)
        assert first.id != second.id
    finally:
        await worker.stop()
