"""Fill missing ComicInfo volumes in a series' CBZs from a volume map.

The map comes from a metadata pass against the series' MangaDex page (see
`service`). Only chapters whose ComicInfo has no volume (absent, empty or
0) are touched, and only their `Volume` element changes: each archive is
rebuilt beside the original with every other entry copied unchanged, then
renamed over it.

Everything here is synchronous filesystem work; callers run it on a worker
thread (series directories often sit on a NAS mount).
"""

from __future__ import annotations

import logging
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from backend.comic_metadata import safe_float
from backend.epub.library import DiskChapter, scan_series_chapters

logger = logging.getLogger(__name__)

MANGADEX_TITLE_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?mangadex\.(?:org|cc)/(?:title|manga)/"
    r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:[/?#]|$)",
    re.IGNORECASE,
)

COMICINFO = "ComicInfo.xml"

# ComicInfo's schema is an ordered sequence, and Volume comes right after
# these elements; a new Volume goes after the last of them present.
_BEFORE_VOLUME = frozenset({"Title", "Series", "Number", "Count"})

# Cap on per-chapter error lines returned to the caller.
MAX_ERRORS = 20


def is_mangadex_title_url(url: str | None) -> bool:
    return bool(url) and MANGADEX_TITLE_URL.match(url.strip()) is not None


def volume_source_url(url: str, metadata_source_url: str | None) -> str | None:
    """The MangaDex title page to read volumes from: the series' own URL
    when it is one, otherwise its metadata source URL when that is one."""
    for candidate in (url, metadata_source_url):
        if candidate and is_mangadex_title_url(candidate):
            return candidate.strip()
    return None


def volumes_by_number(chapter_volumes: Mapping[tuple[str, str], str]) -> dict[float, str]:
    """Key a metadata pass's `(manga, chapter) -> volume` map by numeric
    chapter number, so it matches chapters on disk whatever the series is
    called there ("12", "012" and "12.0" are the same chapter). When the
    source lists a chapter more than once (several languages or scanlation
    groups), the first volume seen wins."""
    out: dict[float, str] = {}
    for (_manga, chapter), volume in chapter_volumes.items():
        value = safe_float(chapter)
        if value is not None and volume:
            out.setdefault(value, volume)
    return out


def lacks_volume(volume: str) -> bool:
    """True when a ComicInfo Volume value means "no volume": empty, or a
    number <= 0 (the packer writes none for volume 0). Other non-numeric
    values were set by hand and are left alone."""
    text = volume.strip()
    if not text:
        return True
    number = safe_float(text)
    return number is not None and number <= 0


def chapters_missing_volume(series_dir: Path, series_name: str) -> tuple[int, list[DiskChapter]]:
    """(numbered chapters on disk, those of them without a volume)."""
    chapters = [ch for ch in scan_series_chapters(series_dir, series_name) if ch.value is not None]
    return len(chapters), [ch for ch in chapters if lacks_volume(ch.volume)]


def set_comicinfo_volume(xml_bytes: bytes, volume: str) -> bytes:
    """ComicInfo.xml with its Volume set to `volume`, everything else kept.

    Unused namespace declarations on the root (xmlns:xsd / xmlns:xsi) are not
    carried over; ComicInfo readers don't need them.
    """
    root = ET.fromstring(xml_bytes)
    element = root.find("Volume")
    if element is None:
        element = ET.Element("Volume")
        index = 0
        for i, child in enumerate(root):
            if child.tag in _BEFORE_VOLUME:
                index = i + 1
        root.insert(index, element)
    element.text = volume
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


class MissingComicInfo(Exception):
    """The archive has no ComicInfo.xml to put a volume in."""


def write_volume(cbz: Path, volume: str) -> None:
    """Set the Volume in `cbz`'s ComicInfo.xml.

    Atomic: a sibling `.part` archive is built and renamed over the original.
    Every other entry is copied with its original compression and timestamp,
    and the file keeps its permissions.
    """
    part = cbz.with_name(cbz.name + ".part")
    with zipfile.ZipFile(cbz) as src:
        try:
            info = src.getinfo(COMICINFO)
        except KeyError:
            raise MissingComicInfo(cbz.name) from None
        new_xml = set_comicinfo_volume(src.read(info), volume)
        try:
            with zipfile.ZipFile(part, "w") as dst:
                for item in src.infolist():
                    data = new_xml if item.filename == COMICINFO else src.read(item)
                    dst.writestr(item, data)
            shutil.copymode(cbz, part)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    part.replace(cbz)


@dataclass
class VolumeFillResult:
    # Numbered chapters on disk.
    chapters: int = 0
    # Of those, chapters that had no volume before the fill.
    missing: int = 0
    filled: int = 0
    # Missing chapters the source has not put in a volume (yet).
    unassigned: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


def fill_volumes(
    chapters: int,
    missing: Iterable[DiskChapter],
    volumes: Mapping[float, str],
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_step: Callable[[str], None] | None = None,
) -> VolumeFillResult:
    """Write a volume into each of the `missing` chapters the map covers.

    One failing archive doesn't stop the rest. `should_cancel` is checked
    between archives; when it fires, the result so far comes back with
    `cancelled` set.
    """
    todo = list(missing)
    result = VolumeFillResult(chapters=chapters, missing=len(todo))
    for ch in todo:
        if should_cancel is not None and should_cancel():
            result.cancelled = True
            break
        volume = volumes.get(ch.value) if ch.value is not None else None
        if not volume:
            result.unassigned += 1
            continue
        try:
            write_volume(ch.path, volume)
        except (OSError, zipfile.BadZipFile, ET.ParseError, MissingComicInfo) as exc:
            logger.warning("volume fill failed for %s", ch.path, exc_info=True)
            result.failed += 1
            reason = "no ComicInfo.xml" if isinstance(exc, MissingComicInfo) else repr(exc)
            line = f"c{ch.number} ({ch.path.name}): {reason}"
            if len(result.errors) < MAX_ERRORS:
                result.errors.append(line)
            if on_step is not None:
                on_step(f"failed: {line}")
            continue
        result.filled += 1
        if on_step is not None:
            on_step(f"vol. {volume}: {ch.path.name}")
    return result
