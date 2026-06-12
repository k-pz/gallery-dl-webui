from pathlib import Path

from backend.comic_metadata import FileRecord
from backend.downloads.outcomes import ChapterSeed, reconcile_outcomes


def _rec(chapter: str, name: str, *, title: str = "", date: str = "") -> FileRecord:
    return FileRecord(
        category="fake",
        manga="S",
        chapter=chapter,
        title=title,
        volume="",
        lang="",
        author="",
        date=date,
        path=Path(f"/dl/S/c{chapter}/{name}"),
    )


def test_downloaded_chapter_counts_image_pages_and_keeps_metadata() -> None:
    needed = [ChapterSeed(name="1", date="2026-01-01")]
    records = [
        _rec("1", "001.jpg", title="Intro", date="2026-01-02"),
        _rec("1", "002.jpg"),
        _rec("1", "thumb.txt"),  # non-image, not counted as a page
    ]
    out = reconcile_outcomes(needed, records, {}, exit_code=0)
    assert len(out) == 1
    assert out[0].name == "1"
    assert out[0].status == "downloaded"
    assert out[0].pages == 2
    assert out[0].title == "Intro"
    assert out[0].date == "2026-01-02"
    assert out[0].error is None


def test_needed_chapter_with_error_is_failed_with_reason() -> None:
    needed = [ChapterSeed(name="7", date="")]
    out = reconcile_outcomes(needed, [], {"7": "403 Forbidden"}, exit_code=1)
    assert out[0].status == "failed"
    assert out[0].error == "403 Forbidden"


def test_needed_chapter_no_records_clean_exit_is_skipped() -> None:
    needed = [ChapterSeed(name="3", date="2026-03-03")]
    out = reconcile_outcomes(needed, [], {}, exit_code=0)
    assert out[0].status == "skipped"
    assert out[0].date == "2026-03-03"
    assert out[0].error is None


def test_needed_chapter_no_records_dirty_exit_is_failed() -> None:
    needed = [ChapterSeed(name="3", date="")]
    out = reconcile_outcomes(needed, [], {}, exit_code=1)
    assert out[0].status == "failed"


def test_records_for_unlisted_chapter_are_synthesized() -> None:
    # Date-less extractor: manifest was empty but files still downloaded.
    out = reconcile_outcomes([], [_rec("9", "001.jpg")], {}, exit_code=0)
    assert len(out) == 1
    assert out[0].name == "9"
    assert out[0].status == "downloaded"
    assert out[0].pages == 1


def test_skipped_chapter_keeps_seed_title() -> None:
    needed = [ChapterSeed(name="3", date="2026-03-03", title="Calm Before")]
    out = reconcile_outcomes(needed, [], {}, exit_code=0)
    assert out[0].status == "skipped"
    assert out[0].title == "Calm Before"


def test_failed_chapter_keeps_seed_title() -> None:
    needed = [ChapterSeed(name="7", date="", title="Storm")]
    out = reconcile_outcomes(needed, [], {"7": "403"}, exit_code=1)
    assert out[0].status == "failed"
    assert out[0].title == "Storm"


def test_downloaded_chapter_prefers_record_title_over_seed() -> None:
    needed = [ChapterSeed(name="1", date="", title="Seeded")]
    records = [_rec("1", "001.jpg", title="From Download")]
    out = reconcile_outcomes(needed, records, {}, exit_code=0)
    assert out[0].title == "From Download"


def test_downloaded_chapter_falls_back_to_seed_title() -> None:
    needed = [ChapterSeed(name="1", date="", title="Seeded")]
    records = [_rec("1", "001.jpg")]  # record has no title
    out = reconcile_outcomes(needed, records, {}, exit_code=0)
    assert out[0].title == "Seeded"
