import asyncio
from pathlib import Path

import pytest

from backend.live_progress import LiveProgress
from backend.postprocess import FileRecord
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


def _make_records_for_chapter(downloads_dir: Path, manga: str, chapter: str) -> list[FileRecord]:
    ch_dir = downloads_dir / "fake" / manga / f"c{chapter}"
    ch_dir.mkdir(parents=True, exist_ok=True)
    records: list[FileRecord] = []
    for name in ("001.jpg", "002.jpg"):
        p = ch_dir / name
        p.write_bytes(b"x")
        records.append(
            FileRecord(
                category="fake",
                manga=manga,
                chapter=chapter,
                title="",
                volume="",
                lang="",
                author="",
                date="",
                path=p,
            )
        )
    return records


async def test_worker_runs_postprocess_when_default_dir_set(
    settings: Settings, storage: Storage, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    default = root / "manga"
    default.mkdir(parents=True)
    await storage.set_app_config(
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(default),
            "delete_raw_after_pack": True,
        }
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg", "fake/S/c1/002.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(storage, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake")
        worker.notify()

        async def packed() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.postprocess_status == "completed"

        await _wait_for(packed)

        row = await storage.get(d.id)
        assert row is not None
        assert row.status == "completed"
        assert row.postprocess_status == "completed"
        assert row.postprocess_chapters_packed == 1
        assert (default / "S" / "S - c001.cbz").is_file()
    finally:
        await worker.stop()


async def test_worker_prefers_per_job_output_dir_over_default(
    settings: Settings, storage: Storage, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    default = root / "manga"
    override = root / "comics"
    default.mkdir(parents=True)
    override.mkdir(parents=True)
    await storage.set_app_config(
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(default),
            "delete_raw_after_pack": True,
        }
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(storage, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake", output_dir=str(override))
        worker.notify()

        async def packed() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.postprocess_status == "completed"

        await _wait_for(packed)

        assert (override / "S" / "S - c001.cbz").is_file()
        assert not (default / "S" / "S - c001.cbz").exists()
    finally:
        await worker.stop()


async def test_worker_creates_missing_per_job_output_dir(
    settings: Settings, storage: Storage, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    root.mkdir()
    new_dir = root / "freshly" / "made"
    await storage.set_app_config(
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
        }
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(storage, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake", output_dir=str(new_dir))
        worker.notify()

        async def packed() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.postprocess_status == "completed"

        await _wait_for(packed)
        assert (new_dir / "S" / "S - c001.cbz").is_file()
    finally:
        await worker.stop()


async def test_worker_skips_postprocess_when_output_dir_not_set(
    settings: Settings, storage: Storage
) -> None:
    # No root, no default, no per-job dir → postprocess should skip cleanly.
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(storage, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.postprocess_status == "skipped"

        await _wait_for(done)
        row = await storage.get(d.id)
        assert row is not None
        assert row.status == "completed"
        assert row.postprocess_status == "skipped"
    finally:
        await worker.stop()


async def test_worker_isolates_postprocess_failure_from_download_status(
    settings: Settings, storage: Storage, tmp_path: Path
) -> None:
    # Point output dir at a file (not a directory) so the postprocess pass fails.
    root = tmp_path / "media"
    root.mkdir()
    blocking_file = root / "not-a-dir"
    blocking_file.write_bytes(b"x")
    await storage.set_app_config(
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(blocking_file),
            "delete_raw_after_pack": False,
        }
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(storage, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await storage.insert_pending("https://example/x", "fake")
        worker.notify()

        async def settled() -> bool:
            row = await storage.get(d.id)
            return row is not None and row.postprocess_status in ("completed", "failed")

        await _wait_for(settled)
        row = await storage.get(d.id)
        assert row is not None
        # Download itself succeeded.
        assert row.status == "completed"
        # Postprocess pass surfaces failure in its own column.
        assert row.postprocess_status == "failed"
        assert row.postprocess_error is not None
    finally:
        await worker.stop()
