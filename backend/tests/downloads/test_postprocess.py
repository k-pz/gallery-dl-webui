import json
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from backend.downloads.postprocess import (
    SERIES_JSON_NAME,
    SERIES_STATUSES,
    FileRecord,
    SeriesMetadata,
    build_comicinfo_xml,
    build_series_json_bytes,
    cbz_target_path,
    chapter_already_packed,
    coerce_record_from_kwdict,
    collect_chapters,
    derive_series_metadata,
    normalize_reading_direction,
    normalize_series_status,
    normalize_tags,
    regenerate_series_metadata,
    run,
    strip_enclosing_brackets,
)

from .._helpers import make_record as _make_record
from .._helpers import write_cbz_with_comicinfo as _write_cbz_with_comicinfo


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


async def test_run_parallel_packing_reserves_distinct_targets(tmp_path: Path) -> None:
    """With max_parallel > 1, two chapters that resolve to the same stem still
    end up at distinct paths via the `(1)` suffix — the in-run reservation set
    plays the same role disk-existence checks do in the sequential path.
    """
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    # Two records that intentionally collide on stem (`S - c001`) — only way
    # to get there is records under different parent dirs sharing manga+chapter.
    ch_a = downloads_dir / "fake" / "S" / "c1"
    ch_b = downloads_dir / "fake" / "S" / "c1_alt"
    ch_a.mkdir(parents=True)
    ch_b.mkdir(parents=True)
    (ch_a / "001.jpg").write_bytes(b"\x89PNG\r\n\x1a\n")
    (ch_b / "001.jpg").write_bytes(b"\x89PNG\r\n\x1a\n")
    records = [
        FileRecord("fake", "S", "1", "", "", "", "", "", ch_a / "001.jpg"),
        FileRecord("fake", "S", "1", "", "", "", "", "", ch_b / "001.jpg"),
    ]

    result = await run(records, output_dir, downloads_dir, delete_raw=False, max_parallel=4)

    assert result.succeeded == 2, result
    assert result.failed == 0, result.error_summary
    assert (output_dir / "S" / "S - c001.cbz").is_file()
    assert (output_dir / "S" / "S - c001 (1).cbz").is_file()


async def test_run_invokes_on_chapter_done_for_every_chapter(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    records = [
        _make_record(downloads_dir, "S", "1", "001.jpg"),
        _make_record(downloads_dir, "S", "2", "001.jpg"),
        _make_record(downloads_dir, "S", "3", "001.jpg"),
    ]
    seen: list[tuple[str, bool]] = []

    await run(
        records,
        output_dir,
        downloads_dir,
        delete_raw=False,
        max_parallel=2,
        on_chapter_done=lambda chapter, ok: seen.append((chapter, ok)),
    )

    assert sorted(seen) == [("1", True), ("2", True), ("3", True)]


async def test_run_applies_custom_naming_template(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    records = [_make_record(downloads_dir, "S", "1", "001.jpg", title="T")]

    await run(
        records,
        output_dir,
        downloads_dir,
        delete_raw=False,
        naming_template="{{ series }}_{{ chapter_number }}{% if title %}_{{ title }}{% endif %}",
    )

    assert (output_dir / "S" / "S_001_T.cbz").is_file()


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


def test_coerce_record_folds_chapter_minor_into_chapter() -> None:
    # gallery-dl splits "700.5" into chapter=700 + chapter_minor=".5" — we
    # rejoin them so the .5 reaches the filename template.
    rec = coerce_record_from_kwdict(
        {"manga": "S", "chapter": 700, "chapter_minor": ".5"},
        Path("/x/a.jpg"),
    )
    assert rec.chapter == "700.5"


def test_coerce_record_does_not_double_apply_chapter_minor() -> None:
    # Some extractors expose a string `chapter` that already contains the
    # decimal — make sure we don't end up with "700.5.5".
    rec = coerce_record_from_kwdict(
        {"manga": "S", "chapter": "700.5", "chapter_minor": ".5"},
        Path("/x/a.jpg"),
    )
    assert rec.chapter == "700.5"


def test_chapter_already_packed_finds_canonical_name(tmp_path: Path) -> None:
    _write_cbz_with_comicinfo(tmp_path / "S" / "S - c001.cbz", "S", "1")
    assert chapter_already_packed(tmp_path, "S", "1") is True


def test_chapter_already_packed_finds_titled_variant(tmp_path: Path) -> None:
    _write_cbz_with_comicinfo(tmp_path / "S" / "S - c001 - First.cbz", "S", "1", "First")
    assert chapter_already_packed(tmp_path, "S", "1") is True


def test_chapter_already_packed_finds_collision_variant(tmp_path: Path) -> None:
    _write_cbz_with_comicinfo(tmp_path / "S" / "S - c001 (1).cbz", "S", "1")
    assert chapter_already_packed(tmp_path, "S", "1") is True


def test_chapter_already_packed_distinguishes_chapter_numbers(tmp_path: Path) -> None:
    # c0011.cbz would be chapter 11 misformatted — must not match c001.
    _write_cbz_with_comicinfo(tmp_path / "S" / "S - c0011.cbz", "S", "11")
    _write_cbz_with_comicinfo(tmp_path / "S" / "S - c001.5.cbz", "S", "1.5")
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


@pytest.mark.parametrize(
    "raw,want",
    [
        ("[Author]", "Author"),
        ('"Author"', "Author"),
        ("'Author'", "Author"),
        ("「Author」", "Author"),
        ('"[Author]"', "Author"),  # nested pairs are unwrapped
        ("(Studio) [Artist]", "(Studio) [Artist]"),  # `(` ... `]` is not a pair
        ("plain", "plain"),
        ("", ""),
        ("  [spaced]  ", "spaced"),
    ],
)
def test_strip_enclosing_brackets(raw: str, want: str) -> None:
    assert strip_enclosing_brackets(raw) == want


def test_coerce_record_strips_brackets_from_author() -> None:
    rec = coerce_record_from_kwdict(
        {"manga": "S", "chapter": "1", "author": "[Some Studio]"},
        Path("/x/a.jpg"),
    )
    assert rec.author == "Some Studio"


def test_coerce_record_captures_description_and_artist() -> None:
    rec = coerce_record_from_kwdict(
        {
            "manga": "S",
            "chapter": "1",
            "author": "Writer",
            "artist": "[Artist]",
            "description": "  A story about X.  ",
        },
        Path("/x/a.jpg"),
    )
    assert rec.description == "A story about X."
    assert rec.artist == "Artist"


def test_coerce_record_falls_back_to_summary_then_abstract() -> None:
    rec = coerce_record_from_kwdict(
        {"manga": "S", "chapter": "1", "summary": "from summary"},
        Path("/x/a.jpg"),
    )
    assert rec.description == "from summary"


def test_normalize_tags_dedupes_and_strips() -> None:
    assert normalize_tags(['"Action"', "action", "[Romance]", "  ", ""]) == [
        "Action",
        "Romance",
    ]


@pytest.mark.parametrize(
    "raw,want",
    [
        ("ltr", "ltr"),
        ("RTL", "rtl"),
        ("  webtoon ", "webtoon"),
        ("vertical", "vertical"),
        ("garbage", "ltr"),
        (None, "ltr"),
    ],
)
def test_normalize_reading_direction(raw: str | None, want: str) -> None:
    assert normalize_reading_direction(raw) == want


def test_build_comicinfo_rtl_maps_manga_yes_and_right_to_left() -> None:
    rec = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/a.jpg"))
    ch = collect_chapters([rec])[0]
    xml_bytes = build_comicinfo_xml(ch, reading_direction="rtl", tags=["action"])
    root = ET.fromstring(xml_bytes)
    assert root.findtext("Manga") == "YesAndRightToLeft"
    assert root.findtext("Tags") == "action"


def test_build_comicinfo_webtoon_adds_format_hint() -> None:
    rec = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/a.jpg"))
    ch = collect_chapters([rec])[0]
    xml_bytes = build_comicinfo_xml(ch, reading_direction="webtoon")
    root = ET.fromstring(xml_bytes)
    assert root.findtext("Manga") == "Yes"
    assert root.findtext("Format") == "Webtoon"


def test_build_comicinfo_emits_description_as_summary() -> None:
    rec = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/a.jpg"), description="About")
    ch = collect_chapters([rec])[0]
    xml_bytes = build_comicinfo_xml(ch)
    root = ET.fromstring(xml_bytes)
    assert root.findtext("Summary") == "About"


def test_build_series_json_omits_blank_fields() -> None:
    meta = SeriesMetadata(name="My Series", description="Plot", tags=["action"])
    payload = json.loads(build_series_json_bytes(meta, total_issues=12))
    assert payload["version"]
    md = payload["metadata"]
    assert md["name"] == "My Series"
    assert md["description_text"] == "Plot"
    assert md["tags"] == ["action"]
    assert md["total_issues"] == 12
    assert md["reading_direction"] == "ltr"
    assert "publisher" not in md  # empty fields are omitted


def test_derive_series_metadata_prefers_overrides() -> None:
    rec = FileRecord(
        "c",
        "S",
        "1",
        "",
        "",
        "en",
        "Writer",
        "2024-03-01",
        Path("/x/a.jpg"),
        description="auto",
    )
    chapters = collect_chapters([rec])
    overrides = SeriesMetadata(
        tags=["[Action]", "action"],
        reading_direction="rtl",
        description="manual",
    )
    meta = derive_series_metadata(chapters, overrides)
    assert meta.tags == ["Action"]
    assert meta.reading_direction == "rtl"
    assert meta.description == "manual"
    assert meta.name == "S"
    assert meta.language == "en"
    assert meta.year == 2024


async def test_run_emits_series_json_with_overrides(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    rec_dir = downloads_dir / "fake" / "Series" / "c1"
    rec_dir.mkdir(parents=True)
    (rec_dir / "001.jpg").write_bytes(b"\xff\xd8\xff")
    records = [
        FileRecord(
            "fake",
            "Series",
            "1",
            "",
            "",
            "en",
            "[Author Studio]",
            "2024-01-15",
            rec_dir / "001.jpg",
            description="An epic tale.",
        )
    ]
    overrides = SeriesMetadata(tags=["[Action]"], reading_direction="rtl")
    result = await run(
        records,
        output_dir,
        downloads_dir,
        delete_raw=False,
        metadata_overrides=overrides,
    )
    assert result.succeeded == 1

    series_json = output_dir / "Series" / SERIES_JSON_NAME
    assert series_json.is_file()
    payload = json.loads(series_json.read_text())
    md = payload["metadata"]
    assert md["name"] == "Series"
    assert md["description_text"] == "An epic tale."
    assert md["writer"] == "Author Studio"
    assert md["tags"] == ["Action"]
    assert md["reading_direction"] == "rtl"
    assert md["language"] == "en"
    assert md["year"] == 2024
    assert md["total_issues"] == 1

    cbz = output_dir / "Series" / "Series - c001.cbz"
    with zipfile.ZipFile(cbz) as zf:
        xml = zf.read("ComicInfo.xml")
    root = ET.fromstring(xml)
    assert root.findtext("Manga") == "YesAndRightToLeft"
    assert root.findtext("Writer") == "Author Studio"
    assert root.findtext("Tags") == "Action"
    assert root.findtext("Summary") == "An epic tale."


def _write_cbz_with_comicinfo_full(
    path: Path,
    series: str,
    chapter: str,
    author: str = "",
    description: str = "",
) -> None:
    from backend.downloads.postprocess import ChapterRecord

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


# ---------------------------------------------------------------------------
# Series status normalisation + propagation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Already canonical — pass through verbatim.
        ("Ongoing", "Ongoing"),
        ("Ended", "Ended"),
        ("Hiatus", "Hiatus"),
        ("Abandoned", "Abandoned"),
        # mangadex / kaliscan / manganelo style lowercase or Title-case strings.
        ("ongoing", "Ongoing"),
        ("publishing", "Ongoing"),
        ("serializing", "Ongoing"),
        ("completed", "Ended"),
        ("COMPLETED", "Ended"),
        ("finished", "Ended"),
        ("hiatus", "Hiatus"),
        ("on_hiatus", "Hiatus"),
        ("on-hiatus", "Hiatus"),
        ("On Hold", "Hiatus"),
        ("cancelled", "Abandoned"),
        ("canceled", "Abandoned"),
        ("discontinued", "Abandoned"),
        ("dropped", "Abandoned"),
        # Garbage in → empty out (caller treats empty as "leave field unset").
        ("Unknown", ""),
        ("???", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_series_status(raw: str | None, expected: str) -> None:
    assert normalize_series_status(raw) == expected


def test_series_statuses_constant_matches_known_set() -> None:
    # Guard so the frontend's hardcoded option list stays in sync.
    assert set(SERIES_STATUSES) == {"Ongoing", "Ended", "Hiatus", "Abandoned"}


def test_coerce_record_from_kwdict_normalises_status(tmp_path: Path) -> None:
    p = tmp_path / "001.jpg"
    p.write_bytes(b"x")
    rec = coerce_record_from_kwdict(
        {"category": "mangadex", "manga": "S", "chapter": "1", "status": "ongoing"}, p
    )
    assert rec.status == "Ongoing"


def test_coerce_record_from_kwdict_falls_back_to_publication_status(tmp_path: Path) -> None:
    p = tmp_path / "001.jpg"
    p.write_bytes(b"x")
    rec = coerce_record_from_kwdict(
        {"category": "fake", "manga": "S", "chapter": "1", "publication_status": "Completed"}, p
    )
    assert rec.status == "Ended"


def test_coerce_record_from_kwdict_drops_unrecognised_status(tmp_path: Path) -> None:
    p = tmp_path / "001.jpg"
    p.write_bytes(b"x")
    rec = coerce_record_from_kwdict(
        {"category": "fake", "manga": "S", "chapter": "1", "status": "weird"}, p
    )
    assert rec.status == ""


def test_collect_chapters_carries_status_from_first_record() -> None:
    rec_a = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/c1/001.jpg"), status="Ongoing")
    rec_b = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/c1/002.jpg"))
    chapters = collect_chapters([rec_a, rec_b])
    assert len(chapters) == 1
    assert chapters[0].status == "Ongoing"


def test_derive_series_metadata_pulls_status_from_chapters() -> None:
    rec = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/a.jpg"), status="Ongoing")
    meta = derive_series_metadata(collect_chapters([rec]))
    assert meta.status == "Ongoing"


def test_derive_series_metadata_override_status_wins_over_chapter() -> None:
    rec = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/a.jpg"), status="Ongoing")
    meta = derive_series_metadata(
        collect_chapters([rec]), SeriesMetadata(status="Ended", tags=[], reading_direction="ltr")
    )
    assert meta.status == "Ended"


def test_derive_series_metadata_blank_override_keeps_chapter_status() -> None:
    """An empty override is the "no per-target preference" case — fall back to what
    the extractor told us rather than blanking it out."""
    rec = FileRecord("c", "S", "1", "", "", "", "", "", Path("/x/a.jpg"), status="Hiatus")
    meta = derive_series_metadata(
        collect_chapters([rec]), SeriesMetadata(status="", tags=[], reading_direction="ltr")
    )
    assert meta.status == "Hiatus"


def test_build_series_json_bytes_emits_ongoing_as_continuing() -> None:
    # Komga's Mylar importer only recognises "Continuing" (→ ONGOING) and
    # "Ended" — emitting our local label "Ongoing" verbatim is ignored.
    meta = SeriesMetadata(name="S", status="Ongoing", tags=[], reading_direction="ltr")
    payload = json.loads(build_series_json_bytes(meta).decode())
    assert payload["metadata"]["status"] == "Continuing"


def test_build_series_json_bytes_emits_ended_unchanged() -> None:
    meta = SeriesMetadata(name="S", status="Ended", tags=[], reading_direction="ltr")
    payload = json.loads(build_series_json_bytes(meta).decode())
    assert payload["metadata"]["status"] == "Ended"


@pytest.mark.parametrize("local_status", ["Hiatus", "Abandoned"])
def test_build_series_json_bytes_omits_states_komga_cannot_import(local_status: str) -> None:
    # Komga's Mylar provider has no mapping for these — emitting them would be
    # silently dropped. The REST push (maintenance/komga.py) handles them.
    meta = SeriesMetadata(name="S", status=local_status, tags=[], reading_direction="ltr")
    payload = json.loads(build_series_json_bytes(meta).decode())
    assert "status" not in payload["metadata"]


def test_build_series_json_bytes_omits_blank_status() -> None:
    meta = SeriesMetadata(name="S", status="", tags=[], reading_direction="ltr")
    payload = json.loads(build_series_json_bytes(meta).decode())
    assert "status" not in payload["metadata"]


async def test_run_writes_ongoing_status_as_continuing(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    rec_dir = downloads_dir / "fake" / "S" / "c1"
    rec_dir.mkdir(parents=True)
    (rec_dir / "001.jpg").write_bytes(b"\xff\xd8\xff")
    records = [
        FileRecord("fake", "S", "1", "", "", "", "", "", rec_dir / "001.jpg", status="Ongoing"),
    ]
    result = await run(records, output_dir, downloads_dir, delete_raw=False)
    assert result.succeeded == 1
    payload = json.loads((output_dir / "S" / SERIES_JSON_NAME).read_text())
    assert payload["metadata"]["status"] == "Continuing"


async def test_run_omits_hiatus_status_from_series_json(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    output_dir = tmp_path / "out"
    rec_dir = downloads_dir / "fake" / "S" / "c1"
    rec_dir.mkdir(parents=True)
    (rec_dir / "001.jpg").write_bytes(b"\xff\xd8\xff")
    records = [
        FileRecord("fake", "S", "1", "", "", "", "", "", rec_dir / "001.jpg", status="Hiatus"),
    ]
    result = await run(records, output_dir, downloads_dir, delete_raw=False)
    assert result.succeeded == 1
    payload = json.loads((output_dir / "S" / SERIES_JSON_NAME).read_text())
    assert "status" not in payload["metadata"]
