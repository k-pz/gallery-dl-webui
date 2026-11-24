import os
import stat
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from backend.volume_fill.library import (
    chapters_missing_volume,
    fill_volumes,
    is_mangadex_title_url,
    lacks_volume,
    set_comicinfo_volume,
    volume_source_url,
    volumes_by_number,
    write_volume,
)
from tests._helpers import png_bytes, write_chapter_cbz

MD = "https://mangadex.org/title/0aea9f43-d4a9-4bf7-bebc-550a512f9b95/some-series"


def _comicinfo(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as zf:
        return ET.fromstring(zf.read("ComicInfo.xml"))


# --- source URLs ------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        MD,
        "https://mangadex.org/title/0aea9f43-d4a9-4bf7-bebc-550a512f9b95",
        "mangadex.org/manga/0AEA9F43-D4A9-4BF7-BEBC-550A512F9B95?tab=chapters",
        "https://www.mangadex.cc/title/0aea9f43-d4a9-4bf7-bebc-550a512f9b95",
    ],
)
def test_mangadex_title_urls_are_recognised(url: str) -> None:
    assert is_mangadex_title_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        None,
        "https://mangadex.org/chapter/0aea9f43-d4a9-4bf7-bebc-550a512f9b95",
        "https://mangadex.org/title/not-a-uuid",
        "https://weebcentral.com/series/01J76XY",
        "https://evil.example/?u=mangadex.org/title/0aea9f43-d4a9-4bf7-bebc-550a512f9b95",
    ],
)
def test_other_urls_are_not_mangadex_titles(url: str | None) -> None:
    assert not is_mangadex_title_url(url)


def test_volume_source_prefers_series_url_then_metadata_source() -> None:
    other = "https://mangadex.org/title/11111111-2222-3333-4444-555555555555"
    assert volume_source_url(MD, other) == MD
    assert volume_source_url("https://weebcentral.com/series/x", other) == other
    assert volume_source_url("https://weebcentral.com/series/x", None) is None
    assert volume_source_url("https://weebcentral.com/series/x", "https://comick.io/x") is None


def test_volumes_by_number_normalises_chapter_numbers_and_keeps_first() -> None:
    volumes = volumes_by_number(
        {
            ("Series (en)", "012"): "2",
            ("Series (es)", "12"): "3",
            ("Series", "12.5"): "2",
            ("Series", "Extra"): "9",
            ("Series", "13"): "",
        }
    )
    assert volumes == {12.0: "2", 12.5: "2"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", True),
        ("  ", True),
        ("0", True),
        ("0.0", True),
        ("-1", True),
        ("3", False),
        ("x", False),
    ],
)
def test_lacks_volume(value: str, expected: bool) -> None:
    assert lacks_volume(value) is expected


# --- ComicInfo rewrite --------------------------------------------------------


def test_set_volume_inserts_after_number_in_schema_order() -> None:
    xml = (
        b"<ComicInfo><Series>S</Series><Title>T</Title><Number>4</Number>"
        b"<Summary>x</Summary></ComicInfo>"
    )
    root = ET.fromstring(set_comicinfo_volume(xml, "2"))
    assert [c.tag for c in root] == ["Series", "Title", "Number", "Volume", "Summary"]
    assert root.findtext("Volume") == "2"
    assert root.findtext("Summary") == "x"


def test_set_volume_replaces_existing_element() -> None:
    xml = b"<ComicInfo><Number>4</Number><Volume>0</Volume></ComicInfo>"
    root = ET.fromstring(set_comicinfo_volume(xml, "7"))
    assert [c.tag for c in root] == ["Number", "Volume"]
    assert root.findtext("Volume") == "7"


def test_write_volume_keeps_pages_compression_and_mode(tmp_path: Path) -> None:
    page = png_bytes(10, 20)
    cbz = write_chapter_cbz(
        tmp_path / "S - c1.cbz", "S", "1", title="One", pages=[("001.png", page)]
    )
    # Re-store the page uncompressed to check each entry keeps its own method.
    with zipfile.ZipFile(cbz) as zf:
        info_xml = zf.read("ComicInfo.xml")
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("ComicInfo.xml", info_xml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("001.png", page, compress_type=zipfile.ZIP_STORED)
    os.chmod(cbz, 0o640)

    write_volume(cbz, "3")

    with zipfile.ZipFile(cbz) as zf:
        assert zf.namelist() == ["ComicInfo.xml", "001.png"]
        assert zf.read("001.png") == page
        assert zf.getinfo("001.png").compress_type == zipfile.ZIP_STORED
    root = _comicinfo(cbz)
    assert root.findtext("Volume") == "3"
    assert root.findtext("Title") == "One"
    assert stat.S_IMODE(cbz.stat().st_mode) == 0o640
    assert not (tmp_path / "S - c1.cbz.part").exists()


# --- fill -----------------------------------------------------------------------


def test_fill_writes_only_missing_volumes_the_source_knows(tmp_path: Path) -> None:
    d = tmp_path / "S"
    write_chapter_cbz(d / "S - c1.cbz", "S", "1", volume="1")
    write_chapter_cbz(d / "S - c2.cbz", "S", "2")
    write_chapter_cbz(d / "S - c3.cbz", "S", "3", volume="0")
    write_chapter_cbz(d / "S - c4.cbz", "S", "4")
    before = (d / "S - c1.cbz").read_bytes()
    steps: list[str] = []

    chapters, missing = chapters_missing_volume(d, "S")
    result = fill_volumes(chapters, missing, {1.0: "9", 2.0: "1", 3.0: "2"}, on_step=steps.append)

    assert (result.chapters, result.missing, result.filled, result.unassigned) == (4, 3, 2, 1)
    assert result.failed == 0
    assert (d / "S - c1.cbz").read_bytes() == before  # had a volume: untouched
    assert _comicinfo(d / "S - c2.cbz").findtext("Volume") == "1"
    assert _comicinfo(d / "S - c3.cbz").findtext("Volume") == "2"
    assert _comicinfo(d / "S - c4.cbz").find("Volume") is None
    assert steps == ["vol. 1: S - c2.cbz", "vol. 2: S - c3.cbz"]
    # The next scan sees the new volumes.
    assert [c.number for c in chapters_missing_volume(d, "S")[1]] == ["4"]


def test_fill_reports_archives_without_comicinfo(tmp_path: Path) -> None:
    d = tmp_path / "S"
    d.mkdir()
    with zipfile.ZipFile(d / "S - c5.cbz", "w") as zf:
        zf.writestr("001.png", png_bytes(1, 1))

    chapters, missing = chapters_missing_volume(d, "S")
    result = fill_volumes(chapters, missing, {5.0: "1"})

    assert (result.filled, result.failed) == (0, 1)
    assert result.errors == ["c5 (S - c5.cbz): no ComicInfo.xml"]


def test_fill_stops_when_cancelled(tmp_path: Path) -> None:
    d = tmp_path / "S"
    for n in ("1", "2"):
        write_chapter_cbz(d / f"S - c{n}.cbz", "S", n)
    chapters, missing = chapters_missing_volume(d, "S")

    result = fill_volumes(chapters, missing, {1.0: "1", 2.0: "1"}, should_cancel=lambda: True)

    assert result.cancelled is True
    assert result.filled == 0
