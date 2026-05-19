import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from backend.downloads.postprocess import (
    FileRecord,
    build_comicinfo_xml,
    cbz_target_path,
    chapter_already_packed,
    coerce_record_from_kwdict,
    collect_chapters,
    run,
)


def _make_record(downloads_dir: Path, manga: str, chapter: str, name: str, **extra) -> FileRecord:
    ch_dir = downloads_dir / "fake" / manga / f"c{chapter}"
    ch_dir.mkdir(parents=True, exist_ok=True)
    path = ch_dir / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")  # arbitrary bytes
    return FileRecord(
        category="fake",
        manga=manga,
        chapter=chapter,
        title=extra.get("title", ""),
        volume=extra.get("volume", ""),
        lang=extra.get("lang", ""),
        author=extra.get("author", ""),
        date=extra.get("date", ""),
        path=path,
    )


async def test_run_packs_chapter_into_cbz(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    records = [
        _make_record(downloads_dir, "My Series", "1", "001.jpg"),
        _make_record(downloads_dir, "My Series", "1", "002.jpg"),
    ]

    result = await run(records, output_dir, downloads_dir, delete_raw=True)

    assert result.total == 1
    assert result.succeeded == 1
    assert result.failed == 0

    cbz = output_dir / "My Series" / "My Series - c001.cbz"
    assert cbz.is_file()
    with zipfile.ZipFile(cbz) as zf:
        names = zf.namelist()
    assert "ComicInfo.xml" in names
    assert sorted([n for n in names if n != "ComicInfo.xml"]) == ["001.jpg", "002.jpg"]


async def test_run_uses_disk_files_when_recorded_extension_is_stale(tmp_path: Path) -> None:
    # gallery-dl rewrites a file's extension mid-download when the body's
    # signature disagrees with the URL — the record captured at handle_url
    # time can therefore point at a name that no longer exists on disk.
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    ch_dir = downloads_dir / "fake" / "My Series" / "c1"
    ch_dir.mkdir(parents=True)
    (ch_dir / "001.jpg").write_bytes(b"\xff\xd8\xff")
    (ch_dir / "002.jpg").write_bytes(b"\xff\xd8\xff")
    stale_records = [
        FileRecord("fake", "My Series", "1", "", "", "", "", "", ch_dir / "001.png"),
        FileRecord("fake", "My Series", "1", "", "", "", "", "", ch_dir / "002.png"),
    ]

    result = await run(stale_records, output_dir, downloads_dir, delete_raw=False)

    assert result.failed == 0
    assert result.succeeded == 1
    with zipfile.ZipFile(output_dir / "My Series" / "My Series - c001.cbz") as zf:
        names = zf.namelist()
    assert sorted(n for n in names if n != "ComicInfo.xml") == ["001.jpg", "002.jpg"]


async def test_run_deletes_raw_when_toggle_on(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    records = [_make_record(downloads_dir, "S", "1", "001.jpg")]
    raw_dir = records[0].path.parent

    await run(records, output_dir, downloads_dir, delete_raw=True)

    assert not raw_dir.exists()


async def test_run_preserves_raw_when_toggle_off(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    records = [_make_record(downloads_dir, "S", "1", "001.jpg")]
    raw_dir = records[0].path.parent

    await run(records, output_dir, downloads_dir, delete_raw=False)

    assert raw_dir.exists()
    assert (raw_dir / "001.jpg").exists()


async def test_run_refuses_rmtree_outside_downloads_dir(tmp_path: Path) -> None:
    real_downloads = tmp_path / "downloads"
    other_root = tmp_path / "other"
    output_dir = tmp_path / "out"
    rec = _make_record(other_root, "S", "1", "001.jpg")

    # downloads_dir does not contain the chapter dir — delete must refuse.
    result = await run([rec], output_dir, real_downloads, delete_raw=True)

    assert result.failed == 1
    assert "not under downloads dir" in (result.error_summary or "")
    # The CBZ may or may not have been created depending on order of operations;
    # what matters is that the raw dir was NOT deleted.
    assert (other_root / "fake" / "S" / "c1").exists()


async def test_run_collision_appends_suffix(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    # Pre-existing CBZ at the canonical path.
    series_dir = output_dir / "S"
    series_dir.mkdir(parents=True)
    (series_dir / "S - c001.cbz").write_bytes(b"existing")

    records = [_make_record(downloads_dir, "S", "1", "001.jpg")]
    await run(records, output_dir, downloads_dir, delete_raw=False)

    assert (series_dir / "S - c001 (1).cbz").is_file()
    assert (series_dir / "S - c001.cbz").read_bytes() == b"existing"


async def test_run_with_no_records_returns_empty_result(tmp_path: Path) -> None:
    result = await run([], tmp_path / "out", tmp_path / "downloads", delete_raw=True)
    assert result.total == 0
    assert result.succeeded == 0


async def test_run_drops_records_without_manga_or_chapter(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    # Missing manga.
    bad_dir = downloads_dir / "x"
    bad_dir.mkdir(parents=True)
    bad_path = bad_dir / "001.jpg"
    bad_path.write_bytes(b"x")
    rec = FileRecord(
        category="fake",
        manga="",
        chapter="1",
        title="",
        volume="",
        lang="",
        author="",
        date="",
        path=bad_path,
    )
    result = await run([rec], output_dir, downloads_dir, delete_raw=False)
    assert result.total == 0


def test_collect_chapters_sorts_by_volume_then_chapter() -> None:
    base = Path("/x")
    records = [
        FileRecord("c", "S", "2", "", "1", "", "", "", base / "v1" / "c2" / "a.jpg"),
        FileRecord("c", "S", "1", "", "2", "", "", "", base / "v2" / "c1" / "a.jpg"),
        FileRecord("c", "S", "1", "", "1", "", "", "", base / "v1" / "c1" / "a.jpg"),
    ]
    chapters = collect_chapters(records)
    assert [(c.volume, c.chapter) for c in chapters] == [("1", "1"), ("1", "2"), ("2", "1")]


def test_cbz_target_path_zero_pads_under_1000() -> None:
    rec = FileRecord("c", "Series", "5", "", "", "", "", "", Path("/x/a.jpg"))
    ch = collect_chapters([rec])[0]
    target = cbz_target_path(Path("/out"), ch)
    assert target == Path("/out/Series/Series - c005.cbz")


def test_cbz_target_path_preserves_fractional() -> None:
    rec = FileRecord("c", "Series", "12.5", "", "", "", "", "", Path("/x/a.jpg"))
    ch = collect_chapters([rec])[0]
    target = cbz_target_path(Path("/out"), ch)
    assert target == Path("/out/Series/Series - c012.5.cbz")


def test_cbz_target_path_includes_title_when_present() -> None:
    rec = FileRecord("c", "Series", "1", "The Beginning", "", "", "", "", Path("/x/a.jpg"))
    ch = collect_chapters([rec])[0]
    target = cbz_target_path(Path("/out"), ch)
    assert target == Path("/out/Series/Series - c001 - The Beginning.cbz")


def test_build_comicinfo_xml_has_required_fields() -> None:
    rec = FileRecord(
        "c",
        "My Series",
        "5",
        "Some Title",
        "2",
        "en",
        "Author Name",
        "2024-01-15",
        Path("/x/a.jpg"),
    )
    ch = collect_chapters([rec])[0]
    ch.pages = [Path("/x/a.jpg"), Path("/x/b.jpg")]

    xml_bytes = build_comicinfo_xml(ch)
    root = ET.fromstring(xml_bytes)

    def _text(tag: str) -> str | None:
        el = root.find(tag)
        return el.text if el is not None else None

    assert _text("Series") == "My Series"
    assert _text("Title") == "Some Title"
    assert _text("Number") == "5"
    assert _text("Volume") == "2"
    assert _text("Writer") == "Author Name"
    assert _text("Penciller") == "Author Name"
    assert _text("LanguageISO") == "en"
    assert _text("Year") == "2024"
    assert _text("Month") == "1"
    assert _text("Day") == "15"
    assert _text("PageCount") == "2"
    assert _text("Manga") == "Yes"


def test_coerce_record_handles_author_dict() -> None:
    rec = coerce_record_from_kwdict(
        {"manga": "S", "chapter": "1", "author": {"name": "Foo"}},
        Path("/x/a.jpg"),
    )
    assert rec.author == "Foo"


def test_coerce_record_handles_author_string() -> None:
    rec = coerce_record_from_kwdict(
        {"manga": "S", "chapter": "1", "author": "Bar"}, Path("/x/a.jpg")
    )
    assert rec.author == "Bar"


def test_coerce_record_handles_datetime_date() -> None:
    rec = coerce_record_from_kwdict(
        {"manga": "S", "chapter": "1", "date": datetime(2024, 3, 7)},
        Path("/x/a.jpg"),
    )
    assert rec.date == "2024-03-07"


def test_coerce_record_handles_missing_fields() -> None:
    rec = coerce_record_from_kwdict({}, Path("/x/a.jpg"))
    assert rec.manga == ""
    assert rec.chapter == ""
    assert rec.author == ""
    assert rec.date == ""


def test_chapter_already_packed_finds_canonical_name(tmp_path: Path) -> None:
    series_dir = tmp_path / "S"
    series_dir.mkdir()
    (series_dir / "S - c001.cbz").write_bytes(b"x")
    assert chapter_already_packed(tmp_path, "S", "1") is True


def test_chapter_already_packed_finds_titled_variant(tmp_path: Path) -> None:
    series_dir = tmp_path / "S"
    series_dir.mkdir()
    (series_dir / "S - c001 - First.cbz").write_bytes(b"x")
    assert chapter_already_packed(tmp_path, "S", "1") is True


def test_chapter_already_packed_finds_collision_variant(tmp_path: Path) -> None:
    series_dir = tmp_path / "S"
    series_dir.mkdir()
    (series_dir / "S - c001 (1).cbz").write_bytes(b"x")
    assert chapter_already_packed(tmp_path, "S", "1") is True


def test_chapter_already_packed_distinguishes_chapter_numbers(tmp_path: Path) -> None:
    series_dir = tmp_path / "S"
    series_dir.mkdir()
    # c0011.cbz would be chapter 11 misformatted — must not match c001.
    (series_dir / "S - c0011.cbz").write_bytes(b"x")
    (series_dir / "S - c001.5.cbz").write_bytes(b"x")
    assert chapter_already_packed(tmp_path, "S", "1") is False


def test_chapter_already_packed_handles_missing_series_dir(tmp_path: Path) -> None:
    assert chapter_already_packed(tmp_path, "Nope", "1") is False


def test_chapter_already_packed_handles_empty_inputs(tmp_path: Path) -> None:
    assert chapter_already_packed(tmp_path, "", "1") is False
    assert chapter_already_packed(tmp_path, "S", "") is False


def test_chapter_already_packed_ignores_non_cbz_files(tmp_path: Path) -> None:
    series_dir = tmp_path / "S"
    series_dir.mkdir()
    (series_dir / "S - c001.txt").write_bytes(b"x")
    assert chapter_already_packed(tmp_path, "S", "1") is False


def test_chapter_already_packed_treats_file_at_series_path_as_missing(tmp_path: Path) -> None:
    # A file (not a dir) sitting where the series dir would be is a no-op.
    (tmp_path / "S").write_bytes(b"x")
    assert chapter_already_packed(tmp_path, "S", "1") is False


@pytest.mark.parametrize(
    "raw,want",
    [
        ("1", "001"),
        ("12", "012"),
        ("100", "100"),
        ("1000", "1000"),
        ("12.5", "012.5"),
        ("not-a-number", "not-a-number"),
    ],
)
def test_chapter_number_formatting(raw: str, want: str) -> None:
    from backend.downloads.postprocess import _format_chapter_number

    assert _format_chapter_number(raw) == want
