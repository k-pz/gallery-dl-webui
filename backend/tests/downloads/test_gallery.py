"""Unit tests for the metadata-only simulation job.

Covers the queue-level shortcut that lets us skip descending into a child
chapter extractor when the manga extractor's `Message.Queue` kwdict already
carries everything we need (manga + chapter + date).
"""

from datetime import datetime

import pytest
from gallery_dl.exception import StopExtraction

from backend.downloads.gallery import _MetadataSimulationJob


def _fresh_job() -> _MetadataSimulationJob:
    """Construct a job without invoking the heavy Job.__init__.

    The handlers only touch the four metadata boxes; sidestepping
    `gallery_dl.job.Job.__init__` means tests don't need a real gallery-dl
    extractor or URL to drive a unit-level assertion.
    """
    job = object.__new__(_MetadataSimulationJob)
    job._series_box = [None]
    job._status_box = [None]
    job._tags_box = [None]
    job._dates_box = [{}]
    return job


def test_capture_returns_true_when_chapter_fields_complete():
    job = _fresh_job()
    captured = job._capture(
        {
            "manga": "Some Series",
            "chapter": 12,
            "chapter_minor": "",
            "date": datetime(2026, 5, 21),
            "status": "Ongoing",
            "tags": ["Action", "Adventure"],
        }
    )
    assert captured is True
    assert job._series_box[0] == "Some Series"
    assert job._status_box[0] == "Ongoing"
    assert job._tags_box[0] == ["Action", "Adventure"]
    assert job._dates_box[0] == {("Some Series", "12"): "2026-05-21"}


def test_capture_returns_false_when_date_missing():
    """Without a date the caller still has to descend into the chapter page."""
    job = _fresh_job()
    captured = job._capture(
        {
            "manga": "Some Series",
            "chapter": 12,
            "tags": ["Action"],
        }
    )
    assert captured is False
    # Series-level fields are banked anyway so the fallback descent only has
    # to fill in the chapter date.
    assert job._series_box[0] == "Some Series"
    assert job._tags_box[0] == ["Action"]
    assert job._dates_box[0] == {}


def test_capture_preserves_minor_chapter_in_date_key():
    job = _fresh_job()
    job._capture(
        {
            "manga": "Some Series",
            "chapter": 700,
            "chapter_minor": ".5",
            "date": datetime(2026, 1, 1),
        }
    )
    assert job._dates_box[0] == {("Some Series", "700.5"): "2026-01-01"}


def test_capture_first_seen_status_wins():
    job = _fresh_job()
    job._capture({"manga": "A", "chapter": 1, "date": datetime(2026, 1, 1), "status": "Ongoing"})
    job._capture({"manga": "A", "chapter": 2, "date": datetime(2026, 1, 2), "status": "Ended"})
    assert job._status_box[0] == "Ongoing"


def test_capture_ignores_unrecognised_status():
    job = _fresh_job()
    job._capture(
        {
            "manga": "A",
            "chapter": 1,
            "date": datetime(2026, 1, 1),
            "status": "Unrecognised Garbage",
        }
    )
    assert job._status_box[0] is None


def test_capture_dedupes_chapter_dates_via_setdefault():
    """If the same (manga, chapter) shows up twice, the first date wins."""
    job = _fresh_job()
    job._capture({"manga": "A", "chapter": 1, "date": datetime(2026, 1, 1)})
    job._capture({"manga": "A", "chapter": 1, "date": datetime(2026, 6, 1)})
    assert job._dates_box[0] == {("A", "1"): "2026-01-01"}


def test_handle_queue_skips_super_when_capture_succeeds(monkeypatch):
    """The core optimisation: a complete queue kwdict means no child spawn."""
    job = _fresh_job()
    super_calls: list[tuple[str, dict]] = []
    # super().handle_queue in _MetadataSimulationJob resolves via MRO to
    # DownloadJob.handle_queue (SimulationJob doesn't override it).
    monkeypatch.setattr(
        "gallery_dl.job.DownloadJob.handle_queue",
        lambda self, url, kwdict: super_calls.append((url, kwdict)),
    )
    job.handle_queue(
        "https://example.com/chapters/abc",
        {"manga": "Some Series", "chapter": 5, "date": datetime(2026, 5, 21)},
    )
    assert super_calls == []
    assert job._dates_box[0] == {("Some Series", "5"): "2026-05-21"}


def test_handle_queue_falls_back_to_super_when_date_missing(monkeypatch):
    job = _fresh_job()
    super_calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "gallery_dl.job.DownloadJob.handle_queue",
        lambda self, url, kwdict: super_calls.append((url, kwdict)),
    )
    job.handle_queue(
        "https://example.com/chapters/abc",
        {"manga": "Some Series", "chapter": 5},
    )
    assert len(super_calls) == 1
    url, kwdict = super_calls[0]
    assert url == "https://example.com/chapters/abc"
    assert kwdict["manga"] == "Some Series"


def test_handle_directory_captures_and_raises_stop_extraction():
    """Reached for top-level chapter URLs and the fallback descent path."""
    job = _fresh_job()
    with pytest.raises(StopExtraction):
        job.handle_directory({"manga": "Some Series", "chapter": 5, "date": datetime(2026, 5, 21)})
    assert job._dates_box[0] == {("Some Series", "5"): "2026-05-21"}


def test_handle_url_is_a_noop():
    """Belt-and-braces: a stray Url must never touch any state or the filesystem."""
    job = _fresh_job()
    job.handle_url(
        "https://example.com/page1.jpg",
        {"manga": "A", "chapter": 1, "extension": "jpg"},
    )
    assert job._series_box[0] is None
    assert job._dates_box[0] == {}


def test_fake_gallery_run_download_returns_chapter_errors():
    from pathlib import Path

    from backend.config import Settings
    from tests.fakes import FakeGallery, FakeGalleryConfig

    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["ch1/001.jpg"]
    config.chapter_errors_for["https://example/x"] = {"1": "boom"}
    config.write_files = False
    settings = Settings(data_dir=Path("/tmp/does-not-matter"))
    gallery = FakeGallery(settings, config=config)

    result = gallery.run_download("https://example/x")
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert result[2] == {"1": "boom"}
