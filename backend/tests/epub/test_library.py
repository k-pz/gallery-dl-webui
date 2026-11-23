import os
import zipfile
from pathlib import Path

import pytest

from backend.epub.library import (
    BookRange,
    DiskChapter,
    SeriesContext,
    StoredBook,
    book_file_path,
    book_fingerprint,
    book_metadata,
    build_series_context,
    plan_books,
    scan_series_chapters,
    suggest_ranges_from_volumes,
    validate_ranges,
)
from tests._helpers import png_bytes, write_chapter_cbz


def _chapter(number: str, **overrides: object) -> DiskChapter:
    value: float | None
    try:
        value = float(number)
    except ValueError:
        value = None
    base: dict[str, object] = {
        "number": number,
        "value": value,
        "title": "",
        "volume": "",
        "date": "",
        "writer": "",
        "penciller": "",
        "language": "",
        "summary": "",
        "pages": 1,
        "path": Path(f"/lib/S/S - c{number}.cbz"),
        "size": 100,
        "mtime_ns": 1,
    }
    base.update(overrides)
    return DiskChapter(**base)  # type: ignore[arg-type]


# --- scan_series_chapters -------------------------------------------------


def test_scan_reads_comicinfo_and_sorts_by_number(tmp_path: Path) -> None:
    d = tmp_path / "Series"
    write_chapter_cbz(d / "Series - c010.cbz", "Series", "10", title="Ten", volume="2")
    write_chapter_cbz(
        d / "Series - c002.5.cbz",
        "Series",
        "2.5",
        pages=[("001.png", png_bytes(1, 1)), ("002.png", png_bytes(1, 1))],
    )
    write_chapter_cbz(d / "Series - c001.cbz", "Series", "1", date="2020-01-05", author="W")
    (d / "notes.txt").write_text("ignore me")

    chapters = scan_series_chapters(d, "Series")

    assert [c.number for c in chapters] == ["1", "2.5", "10"]
    assert [c.value for c in chapters] == [1.0, 2.5, 10.0]
    assert chapters[2].title == "Ten"
    assert chapters[2].volume == "2"
    assert chapters[1].pages == 2
    assert chapters[0].date == "2020-01-05"
    assert chapters[0].writer == "W"


def test_scan_skips_other_series_and_unreadable_archives(tmp_path: Path) -> None:
    d = tmp_path / "Series"
    write_chapter_cbz(d / "Series - c001.cbz", "Series", "1")
    write_chapter_cbz(d / "Other - c001.cbz", "Other", "1")
    (d / "broken.cbz").write_bytes(b"not a zip")
    assert [c.path.name for c in scan_series_chapters(d, "Series")] == ["Series - c001.cbz"]


def test_scan_falls_back_to_stem_without_comicinfo(tmp_path: Path) -> None:
    d = tmp_path / "Series"
    d.mkdir()
    with zipfile.ZipFile(d / "Series - c007 - Title.cbz", "w") as zf:
        zf.writestr("001.png", png_bytes(1, 1))
    with zipfile.ZipFile(d / "random.cbz", "w") as zf:
        zf.writestr("001.png", png_bytes(1, 1))
    chapters = scan_series_chapters(d, "Series")
    assert [(c.number, c.value) for c in chapters] == [("7", 7.0)]


def test_scan_keeps_newest_archive_for_duplicate_numbers(tmp_path: Path) -> None:
    d = tmp_path / "Series"
    old = write_chapter_cbz(d / "Series - c001.cbz", "Series", "1", title="old")
    new = write_chapter_cbz(d / "Series - c001 (1).cbz", "Series", "1.0", title="new")
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new, ns=(2_000_000_000, 2_000_000_000))
    chapters = scan_series_chapters(d, "Series")
    assert [c.title for c in chapters] == ["new"]


def test_scan_non_numeric_chapters_sort_last(tmp_path: Path) -> None:
    d = tmp_path / "Series"
    write_chapter_cbz(d / "a.cbz", "Series", "Extra")
    write_chapter_cbz(d / "b.cbz", "Series", "3")
    chapters = scan_series_chapters(d, "Series")
    assert [(c.number, c.value) for c in chapters] == [("3", 3.0), ("Extra", None)]


def test_scan_missing_directory_is_empty(tmp_path: Path) -> None:
    assert scan_series_chapters(tmp_path / "nope", "Series") == []


def test_scan_picks_up_rewritten_archive(tmp_path: Path) -> None:
    d = tmp_path / "Series"
    path = write_chapter_cbz(d / "Series - c001.cbz", "Series", "1", title="before")
    assert scan_series_chapters(d, "Series")[0].title == "before"
    write_chapter_cbz(path, "Series", "1", title="after, longer title")
    assert scan_series_chapters(d, "Series")[0].title == "after, longer title"


# --- validate_ranges ------------------------------------------------------


def test_validate_ranges_sorts_and_accepts_open_last_book() -> None:
    ordered = validate_ranges([BookRange(11, None), BookRange(1, 10)])
    assert ordered == [BookRange(1, 10), BookRange(11, None)]


@pytest.mark.parametrize(
    ("ranges", "message"),
    [
        ([BookRange(5, 3)], "ends before it starts"),
        ([BookRange(1, None), BookRange(5, 8)], "only the last book can be open-ended"),
        ([BookRange(1, 10), BookRange(10, 20)], "books overlap"),
        ([BookRange(1, 10), BookRange(9.5, 20)], "books overlap"),
    ],
)
def test_validate_ranges_rejects_invalid(ranges: list[BookRange], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_ranges(ranges)


def test_book_range_contains() -> None:
    assert BookRange(1, 5).contains(5)
    assert BookRange(1, 5).contains(2.5)
    assert not BookRange(1, 5).contains(5.5)
    assert BookRange(6, None).contains(999)
    assert not BookRange(1, None).contains(None)


# --- suggest_ranges_from_volumes ------------------------------------------


def test_suggest_one_book_per_volume_plus_open_tail() -> None:
    chapters = [
        _chapter("1", volume="1"),
        _chapter("2", volume="1"),
        _chapter("3", volume="2"),
        _chapter("4", volume="2"),
        _chapter("5"),
        _chapter("6", volume="0"),
        _chapter("Extra", volume="2"),
    ]
    assert suggest_ranges_from_volumes(chapters) == [
        BookRange(1, 2),
        BookRange(3, 4),
        BookRange(5, None),
    ]


def test_suggest_volume_absorbs_following_unvolumed_extras() -> None:
    chapters = [
        _chapter("1", volume="1"),
        _chapter("2", volume="1"),
        _chapter("2.5"),
        _chapter("3", volume="2"),
        _chapter("4"),
    ]
    assert suggest_ranges_from_volumes(chapters) == [
        BookRange(1, 2.5),
        BookRange(3, 3),
        BookRange(4, None),
    ]


def test_suggest_nothing_without_volumes() -> None:
    assert suggest_ranges_from_volumes([_chapter("1"), _chapter("2")]) == []


def test_suggest_nothing_when_volumes_interleave() -> None:
    chapters = [_chapter("1", volume="2"), _chapter("2", volume="1"), _chapter("3", volume="2")]
    assert suggest_ranges_from_volumes(chapters) == []


# --- series context + metadata --------------------------------------------


def test_series_context_precedence() -> None:
    chapters = [
        _chapter("1", summary="chapter summary", writer="Ch Writer", language="ja"),
        _chapter("2", penciller="Ch Artist"),
    ]
    ctx = build_series_context(
        name="Series",
        url="https://example/s",
        series_json={
            "description_text": "json desc",
            "writer": "Json Writer",
            "publisher": "Pub",
            "tags": ["Json Tag"],
            "reading_direction": "rtl",
            "publication_date": "2001-02-03",
        },
        chapters=chapters,
        target_tags=["Target Tag"],
        target_reading_direction=None,
        default_reading_direction="ltr",
    )
    assert ctx.description == "json desc"
    assert ctx.writer == "Json Writer"
    assert ctx.penciller == "Ch Artist"
    assert ctx.publisher == "Pub"
    assert ctx.language == "ja"
    assert ctx.published == "2001-02-03"
    assert ctx.tags == ("Target Tag",)
    assert ctx.reading_direction == "rtl"


def test_series_context_falls_back_to_defaults() -> None:
    ctx = build_series_context(
        name="Series",
        url="u",
        series_json={},
        chapters=[],
        target_tags=[],
        target_reading_direction="webtoon",
        default_reading_direction="ltr",
    )
    assert ctx.reading_direction == "webtoon"
    assert ctx.tags == ()
    assert ctx.description == ""


def _ctx(**overrides: object) -> SeriesContext:
    base: dict[str, object] = {
        "name": "Series",
        "url": "https://example/s",
        "description": "About.",
        "writer": "A Writer, B Writer",
        "penciller": "a writer",
        "language": "en",
        "published": "1999-01-01",
        "tags": ("Action",),
        "reading_direction": "rtl",
    }
    base.update(overrides)
    return SeriesContext(**base)  # type: ignore[arg-type]


def test_book_metadata_fields() -> None:
    chapters = [_chapter("3", date="2010-05-01"), _chapter("4", date="2010-04-01"), _chapter("5")]
    meta = book_metadata(_ctx(), 2, "Series, Vol. 2", chapters)
    assert meta.title == "Series, Vol. 2"
    assert meta.series == "Series"
    assert meta.series_index == 2
    assert meta.authors == ("A Writer", "B Writer")
    assert meta.published == "2010-04-01"
    assert meta.description == "About.\n\nChapters 3–5."  # noqa: RUF001
    assert meta.language == "en"
    assert meta.tags == ("Action",)
    assert meta.reading_direction == "rtl"
    assert meta.source_url == "https://example/s"
    assert meta.identifier.startswith("urn:uuid:")


def test_book_metadata_single_chapter_and_fallbacks() -> None:
    meta = book_metadata(_ctx(description="", language=""), 1, "T", [_chapter("7")])
    assert meta.description == "Chapter 7."
    assert meta.published == "1999-01-01"
    assert meta.language == "und"


def test_book_identifier_is_stable_per_position() -> None:
    chapters = [_chapter("1")]
    a = book_metadata(_ctx(), 1, "T", chapters).identifier
    assert book_metadata(_ctx(), 1, "Other title", [_chapter("2")]).identifier == a
    assert book_metadata(_ctx(), 2, "T", chapters).identifier != a
    assert book_metadata(_ctx(url="https://other"), 1, "T", chapters).identifier != a


def test_fingerprint_tracks_metadata_and_archives() -> None:
    meta = book_metadata(_ctx(), 1, "T", [_chapter("1")])
    base = book_fingerprint(meta, [_chapter("1")])
    assert book_fingerprint(meta, [_chapter("1")]) == base
    assert book_fingerprint(meta, [_chapter("1", mtime_ns=2)]) != base
    assert book_fingerprint(meta, [_chapter("1"), _chapter("2")]) != base
    retitled = book_metadata(_ctx(), 1, "Other", [_chapter("1")])
    assert book_fingerprint(retitled, [_chapter("1")]) != base


def test_book_file_path_uses_position() -> None:
    assert book_file_path(Path("/out"), "A: B", 3) == Path("/out/A_ B/A_ B - Vol. 03.epub")


# --- plan_books -----------------------------------------------------------


def _stored(id_: int, position: int, start: float, end: float | None, **kw: object) -> StoredBook:
    base: dict[str, object] = {
        "id": id_,
        "position": position,
        "title": None,
        "chapter_start": start,
        "chapter_end": end,
        "export_path": None,
        "export_fingerprint": None,
        "exported_at": None,
    }
    base.update(kw)
    return StoredBook(**base)  # type: ignore[arg-type]


def test_plan_books_assigns_chapters_and_statuses(tmp_path: Path) -> None:
    ctx = _ctx()
    chapters = [_chapter("1"), _chapter("2"), _chapter("3"), _chapter("9")]
    first = plan_books(ctx, [_stored(1, 1, 1, 2), _stored(2, 2, 3, None)], chapters, tmp_path)
    assert [c.number for c in first[0].chapters] == ["1", "2"]
    assert [c.number for c in first[1].chapters] == ["3", "9"]
    assert [p.status for p in first] == ["not_exported", "not_exported"]
    assert first[0].title == "Series, Vol. 1"
    assert first[0].path == tmp_path / "Series" / "Series - Vol. 01.epub"

    # Simulate an export of book 1 at its expected path with its fingerprint.
    p = first[0].path
    p.parent.mkdir(parents=True)
    p.write_bytes(b"epub")
    exported = _stored(
        1, 1, 1, 2, export_path=str(p), export_fingerprint=first[0].fingerprint, exported_at="t"
    )
    again = plan_books(ctx, [exported], chapters, tmp_path)
    assert again[0].status == "exported"
    assert again[0].file_exists

    # New chapter in range → outdated.
    grown = plan_books(ctx, [exported], [*chapters, _chapter("1.5")], tmp_path)
    assert grown[0].status == "outdated"

    # Same content but the book moved to a new position (new path) → outdated.
    moved = plan_books(
        ctx,
        [_stored(1, 2, 1, 2, export_path=str(p), export_fingerprint=first[0].fingerprint)],
        chapters,
        tmp_path,
    )
    assert moved[0].status == "outdated"

    # Export file deleted → not exported.
    p.unlink()
    gone = plan_books(ctx, [exported], chapters, tmp_path)
    assert gone[0].status == "not_exported"
    assert not gone[0].file_exists


def test_plan_books_empty_range_and_unnamed_series(tmp_path: Path) -> None:
    plans = plan_books(_ctx(), [_stored(1, 1, 50, 60, title="Custom")], [_chapter("1")], tmp_path)
    assert plans[0].status == "empty"
    assert plans[0].title == "Custom"
    assert plans[0].meta is None
    unnamed = plan_books(None, [_stored(1, 1, 1, None)], [_chapter("1")], tmp_path)
    assert unnamed[0].status == "empty"
    assert unnamed[0].title == "Vol. 1"
