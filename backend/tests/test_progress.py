from pathlib import Path

from backend.progress import (
    chapter_progress,
    chapter_progress_from_completed,
    count_present,
)


def _write(root: Path, *relpaths: str) -> None:
    for rel in relpaths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def test_chapter_progress_groups_by_directory(tmp_path: Path) -> None:
    manifest = [
        "ch1/001.jpg",
        "ch1/002.jpg",
        "ch2/001.jpg",
    ]
    _write(tmp_path, "ch1/001.jpg")

    chapters = chapter_progress(manifest, tmp_path)

    names = [c.name for c in chapters]
    assert names == ["ch1", "ch2"]
    by_name = {c.name: c for c in chapters}
    assert by_name["ch1"].files_total == 2
    assert by_name["ch1"].files_present == 1
    assert by_name["ch2"].files_total == 1
    assert by_name["ch2"].files_present == 0


def test_chapter_progress_matches_on_stem_not_extension(tmp_path: Path) -> None:
    """Simulated extension may differ from the real downloaded extension."""
    manifest = ["ch1/001.jpg"]
    _write(tmp_path, "ch1/001.png")

    chapters = chapter_progress(manifest, tmp_path)

    assert chapters[0].files_present == 1


def test_chapter_progress_handles_missing_directory(tmp_path: Path) -> None:
    manifest = ["never/created.jpg"]

    chapters = chapter_progress(manifest, tmp_path)

    assert chapters[0].files_total == 1
    assert chapters[0].files_present == 0


def test_chapter_progress_root_relpath_uses_empty_name(tmp_path: Path) -> None:
    manifest = ["just_a_file.jpg"]
    _write(tmp_path, "just_a_file.jpg")

    chapters = chapter_progress(manifest, tmp_path)

    assert chapters[0].name == ""
    assert chapters[0].files_present == 1


def test_chapter_progress_preserves_manifest_order(tmp_path: Path) -> None:
    manifest = ["z/1.jpg", "a/1.jpg", "m/1.jpg"]
    chapters = chapter_progress(manifest, tmp_path)
    assert [c.name for c in chapters] == ["z", "a", "m"]


def test_count_present_sums_across_chapters(tmp_path: Path) -> None:
    manifest = ["ch1/a.jpg", "ch1/b.jpg", "ch2/c.jpg"]
    _write(tmp_path, "ch1/a.png", "ch2/c.png")

    assert count_present(manifest, tmp_path) == 2


def test_chapter_progress_from_completed_uses_in_memory_set() -> None:
    manifest = ["ch1/001.jpg", "ch1/002.jpg", "ch2/001.jpg"]
    completed = ["ch1/001.png", "ch2/001.jpg"]

    chapters = chapter_progress_from_completed(manifest, completed)
    by_name = {c.name: c for c in chapters}

    assert by_name["ch1"].files_present == 1
    assert by_name["ch2"].files_present == 1


def test_chapter_progress_from_completed_ignores_unrelated_entries() -> None:
    chapters = chapter_progress_from_completed(["ch1/001.jpg"], ["other/999.jpg"])
    assert chapters[0].files_present == 0
