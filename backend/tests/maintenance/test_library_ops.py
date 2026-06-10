"""Tests for the library-wide CBZ maintenance routines (rename/regen)."""

import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from backend.comic_metadata import (
    SERIES_JSON_NAME,
    ChapterRecord,
    SeriesMetadata,
    build_comicinfo_xml,
)
from backend.maintenance.library_ops import regenerate_series_metadata


def _write_cbz_with_comicinfo_full(
    path: Path,
    series: str,
    chapter: str,
    author: str = "",
    description: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ch = ChapterRecord(
        manga=series,
        chapter=chapter,
        title="",
        volume="",
        lang="",
        author=author,
        date="2024-01-15",
        dir=path.parent,
        pages=[Path("/x/001.jpg")],
        description=description,
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ComicInfo.xml", build_comicinfo_xml(ch))
        zf.writestr("001.jpg", b"x")


def test_regenerate_series_metadata_writes_series_json_and_rewrites_cbz(tmp_path: Path) -> None:
    series_dir = tmp_path / "Series A"
    _write_cbz_with_comicinfo_full(
        series_dir / "Series A - c001.cbz",
        "Series A",
        "1",
        author="[Studio One]",
        description="Tale of action.",
    )
    _write_cbz_with_comicinfo_full(
        series_dir / "Series A - c002.cbz",
        "Series A",
        "2",
        author="Studio One",
    )

    def lookup(name: str) -> SeriesMetadata | None:
        if name.lower().startswith("series a"):
            return SeriesMetadata(
                tags=["Action", "Romance"],
                reading_direction="rtl",
            )
        return None

    result = regenerate_series_metadata([tmp_path], overrides_for=lookup)
    assert result.archives_updated == 2
    assert result.series == 1
    assert result.series_json_written == 1
    assert result.skipped == 0
    assert result.failed == 0

    # Author normalized + reading direction reflected in ComicInfo.
    with zipfile.ZipFile(series_dir / "Series A - c001.cbz") as zf:
        root = ET.fromstring(zf.read("ComicInfo.xml"))
    assert root.findtext("Writer") == "Studio One"
    assert root.findtext("Manga") == "YesAndRightToLeft"
    assert root.findtext("Tags") == "Action, Romance"
    assert root.findtext("Summary") == "Tale of action."

    payload = json.loads((series_dir / SERIES_JSON_NAME).read_text())
    md = payload["metadata"]
    assert md["name"] == "Series A"
    assert md["writer"] == "Studio One"
    assert md["tags"] == ["Action", "Romance"]
    assert md["reading_direction"] == "rtl"
    assert md["total_issues"] == 2


def test_regenerate_series_metadata_skips_archives_without_comicinfo(tmp_path: Path) -> None:
    series_dir = tmp_path / "Bare"
    series_dir.mkdir()
    bare = series_dir / "no-comicinfo.cbz"
    with zipfile.ZipFile(bare, "w") as zf:
        zf.writestr("001.jpg", b"x")
    result = regenerate_series_metadata([tmp_path], overrides_for=lambda _: None)
    assert result.skipped == 1
    assert result.archives_updated == 0


def test_regenerate_series_metadata_applies_chapter_date_lookup(tmp_path: Path) -> None:
    """A non-None return from `chapter_date_for(series, chapter)` overwrites
    the existing Year/Month/Day on the regenerated ComicInfo.xml."""
    series_dir = tmp_path / "Series A"
    # `_write_cbz_with_comicinfo_full` writes a CBZ with date 2024-01-15.
    _write_cbz_with_comicinfo_full(series_dir / "Series A - c001.cbz", "Series A", "1")

    def dates(series: str, chapter: str) -> str | None:
        if series == "Series A" and chapter == "1":
            return "2025-07-21"
        return None

    result = regenerate_series_metadata(
        [tmp_path], overrides_for=lambda _: None, chapter_date_for=dates
    )
    assert result.archives_updated == 1

    with zipfile.ZipFile(series_dir / "Series A - c001.cbz") as zf:
        root = ET.fromstring(zf.read("ComicInfo.xml"))
    assert root.findtext("Year") == "2025"
    assert root.findtext("Month") == "7"
    assert root.findtext("Day") == "21"


def test_regenerate_series_metadata_keeps_existing_date_when_lookup_returns_none(
    tmp_path: Path,
) -> None:
    """A None return from the lookup leaves the existing date alone (so dates
    already captured at download time aren't blanked by a missing rediscovery)."""
    series_dir = tmp_path / "Series A"
    # The helper bakes date 2024-01-15 into the on-disk ComicInfo.xml.
    _write_cbz_with_comicinfo_full(series_dir / "Series A - c001.cbz", "Series A", "1")

    result = regenerate_series_metadata(
        [tmp_path], overrides_for=lambda _: None, chapter_date_for=lambda _s, _c: None
    )
    assert result.archives_updated == 1

    with zipfile.ZipFile(series_dir / "Series A - c001.cbz") as zf:
        root = ET.fromstring(zf.read("ComicInfo.xml"))
    assert root.findtext("Year") == "2024"
    assert root.findtext("Month") == "1"
    assert root.findtext("Day") == "15"


class _RecordingProgressSink:
    """Capture every `total` / `step` call so the regen order can be asserted."""

    def __init__(self) -> None:
        self.total_calls: list[int] = []
        self.steps: list[str] = []

    def total(self, n: int) -> None:
        self.total_calls.append(n)

    def step(self, line: str) -> None:
        self.steps.append(line)


def test_regenerate_series_metadata_writes_series_json_before_chapters(
    tmp_path: Path,
) -> None:
    """The regen flow must emit each series.json before any of that series'
    CBZ archives are rewritten. Downstream importers (Komga) that mtime-watch
    the series.json rely on this ordering: the series-level update lands first
    so per-chapter ComicInfo.xml changes are imported against fresh series
    metadata."""
    series_a = tmp_path / "Series A"
    series_b = tmp_path / "Series B"
    _write_cbz_with_comicinfo_full(series_a / "Series A - c001.cbz", "Series A", "1")
    _write_cbz_with_comicinfo_full(series_a / "Series A - c002.cbz", "Series A", "2")
    _write_cbz_with_comicinfo_full(series_b / "Series B - c001.cbz", "Series B", "1")

    sink = _RecordingProgressSink()
    result = regenerate_series_metadata([tmp_path], overrides_for=lambda _: None, progress=sink)
    assert result.series == 2
    assert result.archives_updated == 3
    assert result.series_json_written == 2

    # For each series, the series.json step must precede every "updated:"
    # step for that series' archives.
    def _index(needle: str) -> int:
        for i, line in enumerate(sink.steps):
            if needle in line:
                return i
        raise AssertionError(f"step not recorded: {needle!r} in {sink.steps!r}")

    series_a_json = _index("series.json: Series A")
    series_a_c1 = _index("updated: Series A/Series A - c001.cbz")
    series_a_c2 = _index("updated: Series A/Series A - c002.cbz")
    assert series_a_json < series_a_c1
    assert series_a_json < series_a_c2

    series_b_json = _index("series.json: Series B")
    series_b_c1 = _index("updated: Series B/Series B - c001.cbz")
    assert series_b_json < series_b_c1
