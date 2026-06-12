from pathlib import Path

import aiosqlite
import pytest

from backend.app_config import service as app_config_service
from backend.comic_metadata import FileRecord
from backend.config import Settings
from backend.downloads import service as downloads_service
from backend.downloads.gallery import MetadataResult
from backend.downloads.live_progress import LiveProgress
from backend.downloads.worker import Worker
from backend.targets import service as targets_service
from tests._helpers import wait_for
from tests.fakes import FakeGallery, FakeGalleryConfig


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data")
    s.downloads_dir.mkdir(parents=True, exist_ok=True)
    return s


async def test_worker_runs_pending_job_to_completion(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.extractor_for["https://example/x"] = "fake"
    # Two files in the same chapter dir → derived chapter count is 1.
    config.manifest_for["https://example/x"] = ["ch1/001.jpg", "ch1/002.jpg"]
    gallery = FakeGallery(settings, config=config)
    live = LiveProgress()
    worker = Worker(db, gallery, live)  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status in ("completed", "failed")

        await wait_for(done)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.status == "completed"
        assert row.exit_code == 0
        # files_expected / chapters_total / files_downloaded all carry the
        # chapter count now (one chapter dir in the manifest above).
        assert row.files_expected == 1
        assert row.chapters_total == 1
        assert gallery.metadata_calls == ["https://example/x"]
        assert gallery.download_calls == ["https://example/x"]
    finally:
        await worker.stop()


async def test_worker_cancels_running_job_mid_download(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    """Cancellation requested mid-flight unwinds gallery-dl and marks the job cancelled."""
    config = FakeGalleryConfig()
    # Six files spread across six chapter dirs; cancel after the first lands
    # so the rest are skipped.
    config.manifest_for["https://example/x"] = [f"ch{i}/001.jpg" for i in range(6)]
    gallery = FakeGallery(settings, config=config)
    live = LiveProgress()
    worker = Worker(db, gallery, live)  # type: ignore[arg-type]

    # Wrap LiveProgress.record so we can request cancellation as soon as the
    # first file completes, deterministically catching the job mid-download.
    original_record = live.record
    cancel_after = {"id": -1}

    def record_and_cancel(download_id: int, relpath: str) -> None:
        original_record(download_id, relpath)
        if download_id == cancel_after["id"]:
            worker.request_cancel(download_id)

    live.record = record_and_cancel  # type: ignore[method-assign]

    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        cancel_after["id"] = d.id
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status in {"cancelled", "completed", "failed"}

        await wait_for(done)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.status == "cancelled"
        assert row.finished_at is not None
        # files_downloaded now tracks chapters touched (chapters_seen, fed by
        # the per-file callback), not files. The fake emits one file per
        # chapter dir; the cancel lands after the first one or two land but
        # before all six.
        assert 1 <= row.files_downloaded < 6
    finally:
        await worker.stop()


async def test_worker_cancel_after_extract_skips_download(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    """A cancel that lands between metadata extract and download is honoured."""
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["ch1/001.jpg"]
    gallery = FakeGallery(settings, config=config)

    # Stamp the cancel during extract_metadata so the worker sees it on the
    # next check (right after extract returns).
    real_extract = gallery.extract_metadata

    def extract_and_request_cancel(url: str) -> MetadataResult:
        result = real_extract(url)
        # The slot puts the job id into `_cancel_flags` before starting extract,
        # so iterating that dict yields the currently-claimed job.
        for active_id in list(worker._cancel_flags.keys()):
            worker.request_cancel(active_id)
        return result

    gallery.extract_metadata = extract_and_request_cancel  # type: ignore[method-assign]

    live = LiveProgress()
    worker = Worker(db, gallery, live)  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status in {"cancelled", "completed", "failed"}

        await wait_for(done)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.status == "cancelled"
        # Download phase was skipped entirely.
        assert gallery.download_calls == []
    finally:
        await worker.stop()


async def test_worker_marks_failed_when_extract_raises(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    class Boom(FakeGallery):
        def extract_metadata(self, url: str) -> MetadataResult:  # type: ignore[override]
            raise RuntimeError("nope")

    gallery = Boom(settings, config=FakeGalleryConfig())
    live = LiveProgress()
    worker = Worker(db, gallery, live)  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "failed"

        await wait_for(done)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.status == "failed"
        assert row.error is not None and "nope" in row.error
    finally:
        await worker.stop()


async def test_worker_captures_series_name_from_metadata(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["a/1.jpg"]
    config.series_name_for["https://example/x"] = "Captured Series"
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)
        refreshed = await targets_service.get(db, target.id)
        assert refreshed is not None
        assert refreshed.name == "Captured Series"
    finally:
        await worker.stop()


async def test_worker_captures_series_name_from_records_when_metadata_lacks_it(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = [
        FileRecord(
            category="fake",
            manga="From Records",
            chapter="1",
            title="",
            volume="",
            lang="",
            author="",
            date="",
            path=settings.downloads_dir / "fake" / "S" / "c1" / "001.jpg",
        )
    ]
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)
        refreshed = await targets_service.get(db, target.id)
        assert refreshed is not None
        assert refreshed.name == "From Records"
    finally:
        await worker.stop()


async def test_worker_clears_live_progress_when_done(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["a/1.jpg"]
    gallery = FakeGallery(settings, config=config)
    live = LiveProgress()
    worker = Worker(db, gallery, live)  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)
        assert live.snapshot(d.id) is None
    finally:
        await worker.stop()


async def test_worker_persists_per_chapter_outcomes(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    # Two chapters discovered; chapter 2 fails (no records + captured error).
    config.chapter_dates_for["https://example/x"] = {
        ("S", "1"): "2026-01-01",
        ("S", "2"): "2026-01-02",
    }
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg", "fake/S/c1/002.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    config.chapter_errors_for["https://example/x"] = {"2": "403 Forbidden"}
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.chapters_discovered == 2
        assert row.chapters_total == 2  # needed
        assert row.chapters_failed == 1
        outcomes = await downloads_service.get_chapter_outcomes(db, d.id)
        by_name = {o.name: o for o in outcomes}
        assert by_name["1"].status == "downloaded"
        assert by_name["1"].pages == 2
        assert by_name["2"].status == "failed"
        assert by_name["2"].error == "403 Forbidden"
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
    settings: Settings, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    default = root / "manga"
    default.mkdir(parents=True)
    await app_config_service.set_many(
        db,
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(default),
            "delete_raw_after_pack": True,
        },
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg", "fake/S/c1/002.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def packed() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status == "completed"

        await wait_for(packed)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.status == "completed"
        assert row.postprocess_status == "completed"
        assert row.postprocess_chapters_packed == 1
        assert (default / "S" / "S - c001.cbz").is_file()
    finally:
        await worker.stop()


async def test_worker_prefers_per_job_output_dir_over_default(
    settings: Settings, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    default = root / "manga"
    override = root / "comics"
    default.mkdir(parents=True)
    override.mkdir(parents=True)
    await app_config_service.set_many(
        db,
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(default),
            "delete_raw_after_pack": True,
        },
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", output_dir=str(override)
        )
        worker.notify()

        async def packed() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status == "completed"

        await wait_for(packed)

        assert (override / "S" / "S - c001.cbz").is_file()
        assert not (default / "S" / "S - c001.cbz").exists()
    finally:
        await worker.stop()


async def test_worker_creates_missing_per_job_output_dir(
    settings: Settings, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    root.mkdir()
    new_dir = root / "freshly" / "made"
    await app_config_service.set_many(
        db,
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
        },
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", output_dir=str(new_dir)
        )
        worker.notify()

        async def packed() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status == "completed"

        await wait_for(packed)
        assert (new_dir / "S" / "S - c001.cbz").is_file()
    finally:
        await worker.stop()


async def test_worker_skips_postprocess_when_output_dir_not_set(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    # No root, no default, no per-job dir → postprocess should skip cleanly.
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status == "skipped"

        await wait_for(done)
        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.status == "completed"
        assert row.postprocess_status == "skipped"
    finally:
        await worker.stop()


async def test_worker_skips_already_packed_chapter_for_watched_target(
    settings: Settings, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    """A watched target's subsequent poll should drop chapters whose CBZ
    already lives in the output dir, both from the manifest and the download."""
    root = tmp_path / "media"
    default = root / "manga"
    default.mkdir(parents=True)
    # Pre-existing CBZ for chapter 1 — should be skipped this run.
    series_dir = default / "S"
    series_dir.mkdir()
    (series_dir / "S - c001.cbz").write_bytes(b"already-packed")
    await app_config_service.set_many(
        db,
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(default),
            "delete_raw_after_pack": True,
        },
    )

    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = [
        "fake/S/c1/001.jpg",
        "fake/S/c1/002.jpg",
        "fake/S/c2/001.jpg",
    ]
    config.records_for["https://example/x"] = [
        *_make_records_for_chapter(settings.downloads_dir, "S", "1"),
        *_make_records_for_chapter(settings.downloads_dir, "S", "2"),
    ]
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        await targets_service.update(db, target.id, watched=True)
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def packed() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status in ("completed", "failed")

        await wait_for(packed)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.status == "completed"
        # Only c2 should appear in the manifest — c1 was filtered out.
        # The manifest now stores chapter names (one row per chapter).
        manifest = await downloads_service.get_manifest(db, d.id)
        assert manifest == ["2"]
        # And only c2 should have been newly packed.
        assert row.postprocess_chapters_packed == 1
        # The pre-existing CBZ wasn't overwritten.
        assert (series_dir / "S - c001.cbz").read_bytes() == b"already-packed"
        # And c2's CBZ shows up.
        assert (series_dir / "S - c002.cbz").is_file()
    finally:
        await worker.stop()


async def test_worker_does_not_skip_for_unwatched_target(
    settings: Settings, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    """Unwatched targets keep the existing re-download behavior — gallery-dl's
    own archive.db is still the source of truth there."""
    root = tmp_path / "media"
    default = root / "manga"
    default.mkdir(parents=True)
    series_dir = default / "S"
    series_dir.mkdir()
    (series_dir / "S - c001.cbz").write_bytes(b"old")
    await app_config_service.set_many(
        db,
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(default),
            "delete_raw_after_pack": True,
        },
    )

    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        # Target is NOT watched.
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def packed() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status in ("completed", "failed")

        await wait_for(packed)

        manifest = await downloads_service.get_manifest(db, d.id)
        # Full chapter list preserved (one chapter row, since c1 wasn't filtered).
        assert manifest == ["1"]
    finally:
        await worker.stop()


async def test_worker_isolates_postprocess_failure_from_download_status(
    settings: Settings, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    # Point output dir at a file (not a directory) so the postprocess pass fails.
    root = tmp_path / "media"
    root.mkdir()
    blocking_file = root / "not-a-dir"
    blocking_file.write_bytes(b"x")
    await app_config_service.set_many(
        db,
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(blocking_file),
            "delete_raw_after_pack": False,
        },
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def settled() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status in ("completed", "failed")

        await wait_for(settled)
        row = await downloads_service.get(db, d.id)
        assert row is not None
        # Download itself succeeded.
        assert row.status == "completed"
        # Postprocess pass surfaces failure in its own column.
        assert row.postprocess_status == "failed"
        assert row.postprocess_error is not None
    finally:
        await worker.stop()


async def test_worker_persists_series_published_at_from_metadata_pass(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    """The sim pass discovers the full chapter list; the earliest chapter date
    lands on the target row as the series' first-publication date."""
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c250/001.jpg"]
    config.chapter_dates_for["https://example/x"] = {
        ("S", "250"): "2024-06-01",
        ("S", "1"): "2010-02-15",
    }
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)
        refreshed = await targets_service.get(db, target.id)
        assert refreshed is not None
        assert refreshed.series_published_at == "2010-02-15"
    finally:
        await worker.stop()


async def test_incremental_download_keeps_series_publish_year_in_series_json(
    settings: Settings, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    """An incremental download whose records only carry the newest chapter must
    not restamp series.json with that chapter's year — the stored
    first-publication date wins."""
    import json

    root = tmp_path / "media"
    default = root / "manga"
    default.mkdir(parents=True)
    await app_config_service.set_many(
        db,
        {
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(default),
            "delete_raw_after_pack": True,
        },
    )
    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["fake/S/c250/001.jpg", "fake/S/c250/002.jpg"]
    # Upstream knows the full history back to 2010…
    config.chapter_dates_for["https://example/x"] = {
        ("S", "250"): "2024-06-01",
        ("S", "1"): "2010-02-15",
    }
    # …but this download only fetches the fresh 2024 chapter.
    records = _make_records_for_chapter(settings.downloads_dir, "S", "250")
    config.records_for["https://example/x"] = [
        FileRecord(**{**rec.__dict__, "date": "2024-06-01"}) for rec in records
    ]
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def packed() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.postprocess_status == "completed"

        await wait_for(packed)

        payload = json.loads((default / "S" / "series.json").read_text())
        assert payload["metadata"]["publication_date"] == "2010-02-15"
        assert payload["metadata"]["year"] == 2010
    finally:
        await worker.stop()


async def test_worker_seeds_chapter_titles_from_metadata_pass(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.chapter_dates_for["https://example/x"] = {
        ("S", "1"): "2026-01-01",
        ("S", "2"): "2026-01-02",
    }
    config.chapter_titles_for["https://example/x"] = {
        ("S", "1"): "Intro",
        ("S", "2"): "Rising Action",
    }
    # Nothing downloads (clean exit, no records): both chapters settle as
    # skipped — exactly the case where titles used to be lost.
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)

        outcomes = await downloads_service.get_chapter_outcomes(db, d.id)
        by_name = {o.name: o for o in outcomes}
        assert by_name["1"].title == "Intro"
        assert by_name["2"].title == "Rising Action"
    finally:
        await worker.stop()


async def test_worker_fills_titles_from_metadata_source_url(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    # Original source: dates but no titles.
    config.chapter_dates_for["https://example/x"] = {("S", "1"): "2026-01-01"}
    # Alternate source: same chapter numbers under a different series name.
    config.chapter_dates_for["https://alt/x"] = {("S Alt", "1"): "2026-01-01"}
    config.chapter_titles_for["https://alt/x"] = {("S Alt", "1"): "Intro"}
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        await targets_service.update(db, target.id, metadata_source_url="https://alt/x")
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)

        outcomes = await downloads_service.get_chapter_outcomes(db, d.id)
        assert outcomes[0].title == "Intro"
        assert "https://alt/x" in gallery.metadata_calls
    finally:
        await worker.stop()


async def test_worker_skips_metadata_source_when_titles_complete(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.chapter_dates_for["https://example/x"] = {("S", "1"): "2026-01-01"}
    config.chapter_titles_for["https://example/x"] = {("S", "1"): "Already Here"}
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        await targets_service.update(db, target.id, metadata_source_url="https://alt/x")
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)

        # No wasted upstream fetch when the original source already has titles.
        assert "https://alt/x" not in gallery.metadata_calls
    finally:
        await worker.stop()


async def test_worker_survives_failing_metadata_source_lookup(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.chapter_dates_for["https://example/x"] = {("S", "1"): "2026-01-01"}
    config.metadata_error_for["https://alt/x"] = RuntimeError("alt source down")
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        await targets_service.update(db, target.id, metadata_source_url="https://alt/x")
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await wait_for(done)

        outcomes = await downloads_service.get_chapter_outcomes(db, d.id)
        assert outcomes[0].title == ""
    finally:
        await worker.stop()
