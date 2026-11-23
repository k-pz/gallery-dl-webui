"""Shared test helpers — used by both unit and integration tests."""

from __future__ import annotations

import asyncio
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from backend.comic_metadata import (
    ChapterRecord,
    FileRecord,
    build_comicinfo_xml,
)


async def wait_for(predicate: Callable[[], Awaitable[bool]], timeout: float = 2.0) -> None:
    """Poll an async predicate until it returns true or the timeout expires."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out waiting for condition")


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


def png_bytes(width: int, height: int) -> bytes:
    """Smallest byte string `sniff_image` reads as a PNG of the given size."""
    ihdr = width.to_bytes(4) + height.to_bytes(4) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def jpeg_bytes(width: int, height: int) -> bytes:
    """A JPEG header (SOI + APP0 + SOF0) carrying the given frame size."""
    app0 = b"\xff\xe0" + (16).to_bytes(2) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = (
        b"\xff\xc0"
        + (17).to_bytes(2)
        + b"\x08"
        + height.to_bytes(2)
        + width.to_bytes(2)
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def write_chapter_cbz(
    path: Path,
    series: str,
    chapter: str,
    *,
    pages: list[tuple[str, bytes]] | None = None,
    title: str = "",
    volume: str = "",
    date: str = "",
    author: str = "",
    artist: str = "",
    lang: str = "",
    description: str = "",
) -> Path:
    """Write a CBZ with ComicInfo.xml and real (header-only) page images."""
    path.parent.mkdir(parents=True, exist_ok=True)
    page_list = pages if pages is not None else [("001.png", png_bytes(800, 1200))]
    ch = ChapterRecord(
        manga=series,
        chapter=chapter,
        title=title,
        volume=volume,
        lang=lang,
        author=author,
        date=date,
        dir=path.parent,
        pages=[Path(name) for name, _ in page_list],
        description=description,
        artist=artist,
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ComicInfo.xml", build_comicinfo_xml(ch))
        for name, data in page_list:
            zf.writestr(name, data)
    return path
