import asyncio
from pathlib import Path

import pytest

from backend.live_progress import LiveProgress
from backend.settings import Settings
from backend.storage import Storage
from backend.worker import Worker

from .fakes import FakeGallery, FakeGalleryConfig


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data")
    s.downloads_dir.mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture
async def storage(settings: Settings):
    s = await Storage.open(settings.data_dir / "jobs.db")
    try:
        yield s
    finally:
        await s.close()


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out waiting for condition")


async def test_worker_runs_pending_job_to_completion(settings: Settings, storage: Storage) -> None:
    config = FakeGalleryConfig()
    config.extractor_for["https://example/x"] = "fake"
    config.manifest_for["https://example/x"] = ["ch1/001.jpg", "ch1/002.jpg"]
    gallery = FakeGallery(settings, config=config)
    live = LiveProgress()
    worker = Worker(storage, gallery, live)  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.status in ("completed", "failed")

        await _wait_for(done)

        row = await storage.get(d.id)
        assert row is not None
        assert row.status == "completed"
        assert row.exit_code == 0
        assert row.files_expected == 2
        assert row.files_downloaded == 2
        assert gallery.extract_calls == ["https://example/x"]
        assert gallery.download_calls == ["https://example/x"]
    finally:
        await worker.stop()


async def test_worker_marks_failed_when_extract_raises(
    settings: Settings, storage: Storage
) -> None:
    class Boom(FakeGallery):
        def extract_manifest(self, url: str) -> list[str]:  # type: ignore[override]
            raise RuntimeError("nope")

    gallery = Boom(settings, config=FakeGalleryConfig())
    live = LiveProgress()
    worker = Worker(storage, gallery, live)  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.status == "failed"

        await _wait_for(done)

        row = await storage.get(d.id)
        assert row is not None
        assert row.status == "failed"
        assert row.error is not None and "nope" in row.error
    finally:
        await worker.stop()


async def test_worker_clears_live_progress_when_done(settings: Settings, storage: Storage) -> None:
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["a/1.jpg"]
    gallery = FakeGallery(settings, config=config)
    live = LiveProgress()
    worker = Worker(storage, gallery, live)  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.status == "completed"

        await _wait_for(done)
        assert live.snapshot(d.id) is None
    finally:
        await worker.stop()
