"""Shared test helpers — used by both unit and integration tests."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from backend.downloads.postprocess import (
    ChapterRecord,
    FileRecord,
    build_comicinfo_xml,
)


def make_record(
    downloads_dir: Path,
    manga: str,
    chapter: str,
    name: str,
    **extra: Any,
) -> FileRecord:
    """Build a FileRecord whose `path` points at an on-disk fake page."""
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


def write_cbz_with_comicinfo(path: Path, series: str, chapter: str, title: str = "") -> None:
    """Write a minimal valid CBZ with a ComicInfo.xml derived from a ChapterRecord."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ch = ChapterRecord(
        manga=series,
        chapter=chapter,
        title=title,
        volume="",
        lang="",
        author="",
        date="",
        dir=path.parent,
        pages=[Path("/x/001.jpg")],
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ComicInfo.xml", build_comicinfo_xml(ch))
        zf.writestr("001.jpg", b"x")
