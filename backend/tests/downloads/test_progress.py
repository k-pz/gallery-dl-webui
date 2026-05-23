from pathlib import Path

from backend.downloads.progress import (
    chapter_progress,
    chapter_progress_from_completed,
    count_present_chapters,
)


def test_chapter_progress_emits_one_entry_per_chapter(tmp_path: Path) -> None:
    chapters = chapter_progress(["1", "2", "3"], tmp_path)

    assert [c.name for c in chapters] == ["1", "2", "3"]
    # Each chapter row collapses to a single "expected file" so existing
    # files_present/files_total accounting keeps the same arithmetic.
    assert all(c.files_total == 1 for c in chapters)


def test_chapter_progress_marks_all_downloading_when_not_settled(tmp_path: Path) -> None:
    chapters = chapter_progress(["1", "2"], tmp_path, download_status="running")
    assert [c.stage for c in chapters] == ["downloading", "downloading"]
    assert all(c.files_present == 0 for c in chapters)


def test_chapter_progress_marks_all_completed_when_settled(tmp_path: Path) -> None:
    chapters = chapter_progress(
        ["1", "2"],
        tmp_path,
        download_status="completed",
        postprocess_status="completed",
    )
    assert [c.stage for c in chapters] == ["completed", "completed"]
    assert all(c.files_present == 1 for c in chapters)


def test_chapter_progress_completed_when_postprocess_skipped(tmp_path: Path) -> None:
    """No postprocess_root configured → postprocess_status="skipped" is terminal."""
    chapters = chapter_progress(
        ["1"], tmp_path, download_status="completed", postprocess_status="skipped"
    )
    assert chapters[0].stage == "completed"


def test_chapter_progress_completed_when_download_terminal_no_postprocess(tmp_path: Path) -> None:
    chapters = chapter_progress(["1"], tmp_path, download_status="cancelled")
    assert chapters[0].stage == "completed"


def test_chapter_progress_from_completed_counts_unique_chapter_dirs() -> None:
    chapters = chapter_progress_from_completed(
        ["1", "2", "3"],
        ["fake/S/c1/001.jpg", "fake/S/c1/002.jpg", "fake/S/c2/001.jpg"],
    )

    # Two unique parent dirs → first two chapter rows marked downloaded,
    # the rest still downloading.
    assert chapters[0].stage == "downloaded"
    assert chapters[1].stage == "downloaded"
    assert chapters[2].stage == "downloading"
    assert chapters[0].files_present == 1
    assert chapters[2].files_present == 0


def test_chapter_progress_from_completed_promotes_to_processing_during_postprocess() -> None:
    chapters = chapter_progress_from_completed(
        ["1", "2"],
        ["fake/S/c1/001.jpg", "fake/S/c2/001.jpg"],
        download_status="completed",
        postprocess_status="running",
    )
    assert chapters[0].stage == "processing"
    assert chapters[1].stage == "processing"


def test_chapter_progress_from_completed_marks_completed_when_settled() -> None:
    chapters = chapter_progress_from_completed(
        ["1"], [], download_status="completed", postprocess_status="completed"
    )
    assert chapters[0].stage == "completed"
    assert chapters[0].files_present == 1


def test_chapter_progress_from_completed_handles_empty_record_stream() -> None:
    chapters = chapter_progress_from_completed(["1", "2"], [])
    assert all(c.stage == "downloading" for c in chapters)
    assert all(c.files_present == 0 for c in chapters)


def test_count_present_chapters_uniques_by_parent_dir() -> None:
    paths = [
        Path("/d/fake/S/c1/001.jpg"),
        Path("/d/fake/S/c1/002.jpg"),
        Path("/d/fake/S/c2/001.jpg"),
    ]
    assert count_present_chapters(paths) == 2


def test_count_present_chapters_empty() -> None:
    assert count_present_chapters([]) == 0
