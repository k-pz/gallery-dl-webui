"""Glue between a series' packed CBZs on disk and the EPUB builder.

Scans a series directory into chapter records (read from each CBZ's
ComicInfo.xml), assigns chapters to the user's book ranges, assembles each
book's metadata from the series-level sources, and fingerprints the result
so the UI can tell whether an earlier export is still current.

Everything here is synchronous filesystem work; the router runs it on a
worker thread (series directories often sit on a NAS mount).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from backend.comic_metadata import (
    IMAGE_SUFFIXES,
    chapter_from_comicinfo,
    clean_person_names,
    earliest_date,
    normalize_reading_direction,
    normalize_tags,
    safe_float,
    sanitize,
)
from backend.epub.builder import EpubChapter, EpubMetadata, chapter_label

logger = logging.getLogger(__name__)

# Bump when the builder's output changes in a way that should flag every
# existing export as outdated.
BUILD_FORMAT_VERSION = 1

BookStatus = Literal["empty", "not_exported", "outdated", "exported"]


@dataclass(frozen=True)
class DiskChapter:
    """One packed chapter archive, as read from its ComicInfo.xml."""

    number: str
    # Numeric chapter number; None for non-numeric numbers (e.g. "Extra"),
    # which can't fall inside a book's range.
    value: float | None
    title: str
    volume: str
    date: str
    writer: str
    penciller: str
    language: str
    summary: str
    pages: int
    path: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _CbzInfo:
    series: str | None
    number: str
    title: str
    volume: str
    date: str
    writer: str
    penciller: str
    language: str
    summary: str
    pages: int


# Parsed CBZ headers keyed by (path, size, mtime_ns): reopening every archive
# of a large series on each overview request is slow over a network mount,
# and an unchanged file can't have changed metadata.
_INFO_CACHE: dict[tuple[str, int, int], _CbzInfo | None] = {}
_INFO_CACHE_LIMIT = 20_000


def _read_cbz_info(path: Path) -> _CbzInfo | None:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            xml_bytes = zf.read("ComicInfo.xml") if "ComicInfo.xml" in names else None
    except OSError, zipfile.BadZipFile:
        return None
    pages = sum(1 for n in names if Path(n).suffix.lower() in IMAGE_SUFFIXES)
    root: ET.Element | None = None
    if xml_bytes is not None:
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            root = None
    if root is None:
        return _CbzInfo(None, "", "", "", "", "", "", "", "", pages)
    try:
        rec = chapter_from_comicinfo(path, root)
    except ValueError:
        # Malformed Year/Month/Day; keep the rest by dropping the date.
        for tag in ("Year", "Month", "Day"):
            for el in root.findall(tag):
                root.remove(el)
        rec = chapter_from_comicinfo(path, root)
    return _CbzInfo(
        series=root.findtext("Series"),
        number=rec.chapter.strip(),
        title=rec.title.strip(),
        volume=rec.volume.strip(),
        date=rec.date,
        writer=rec.author,
        penciller=rec.artist,
        language=rec.lang,
        summary=rec.description,
        pages=pages,
    )


def _cached_info(path: Path, size: int, mtime_ns: int) -> _CbzInfo | None:
    key = (str(path), size, mtime_ns)
    if key in _INFO_CACHE:
        return _INFO_CACHE[key]
    info = _read_cbz_info(path)
    if len(_INFO_CACHE) >= _INFO_CACHE_LIMIT:
        _INFO_CACHE.clear()
    _INFO_CACHE[key] = info
    return info


def _normalize_number(token: str) -> str:
    """'001' → '1', '012.5' → '12.5'; non-numeric tokens pass through."""
    value = safe_float(token)
    if value is None:
        return token
    if value.is_integer():
        return str(int(value))
    return token.lstrip("0") or token


def scan_series_chapters(series_dir: Path, series_name: str) -> list[DiskChapter]:
    """Every packed chapter of `series_name` under `series_dir`, in chapter order.

    Mirrors the packer's ownership rule: a CBZ belongs to the series when its
    ComicInfo `Series` sanitizes to the directory's series name, or — for
    archives without usable ComicInfo — when its stem matches the default
    `<series> - c<number>` naming. When several archives carry the same
    chapter number (re-pack collision variants), the most recently modified
    one wins.
    """
    series_key = sanitize(series_name)
    stem_prefix = f"{series_key} - c"
    try:
        children = list(series_dir.iterdir())
    except FileNotFoundError, NotADirectoryError:
        return []
    by_number: dict[float | str, DiskChapter] = {}
    for child in children:
        if child.suffix.lower() != ".cbz":
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        if not child.is_file():
            continue
        info = _cached_info(child, stat.st_size, stat.st_mtime_ns)
        if info is None:
            continue
        number = ""
        if info.series is not None:
            if sanitize(info.series) != series_key:
                continue
            number = info.number
        if not number:
            if not child.stem.startswith(stem_prefix):
                continue
            number = _normalize_number(child.stem[len(stem_prefix) :].split(" ", 1)[0])
        if not number:
            continue
        value = safe_float(number)
        chapter = DiskChapter(
            number=number,
            value=value,
            title=info.title,
            volume=info.volume,
            date=info.date,
            writer=info.writer,
            penciller=info.penciller,
            language=info.language,
            summary=info.summary,
            pages=info.pages,
            path=child,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )
        key: float | str = value if value is not None else number.casefold()
        existing = by_number.get(key)
        if existing is None or chapter.mtime_ns > existing.mtime_ns:
            by_number[key] = chapter
    return sorted(by_number.values(), key=chapter_sort_key)


def chapter_sort_key(ch: DiskChapter) -> tuple[bool, float, str]:
    return (ch.value is None, ch.value if ch.value is not None else 0.0, ch.number)


@dataclass(frozen=True)
class BookRange:
    start: float
    end: float | None

    def contains(self, value: float | None) -> bool:
        if value is None:
            return False
        return value >= self.start and (self.end is None or value <= self.end)


def validate_ranges(ranges: Sequence[BookRange]) -> list[BookRange]:
    """Sort ranges by start and check they form a valid, disjoint book list.

    Raises ValueError with a user-facing message otherwise. Only the last
    book may be open-ended (its end is None).
    """
    ordered = sorted(ranges, key=lambda r: r.start)
    for r in ordered:
        if r.end is not None and r.end < r.start:
            raise ValueError(
                f"book starting at chapter {format_number(r.start)} ends before it starts"
            )
    for prev, nxt in pairwise(ordered):
        if prev.end is None:
            raise ValueError(
                f"only the last book can be open-ended; the book starting at chapter "
                f"{format_number(prev.start)} needs an end chapter"
            )
        if nxt.start <= prev.end:
            raise ValueError(
                f"books overlap: chapter {format_number(nxt.start)} is already in the book "
                f"ending at chapter {format_number(prev.end)}"
            )
    return ordered


def format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else repr(value)


def suggest_ranges_from_volumes(chapters: Iterable[DiskChapter]) -> list[BookRange]:
    """One book per ComicInfo volume, plus an open-ended book for the
    not-yet-collected chapters after the last volume. Chapters without a
    volume that sit between two volumes join the earlier one.

    Returns an empty list when no chapter has a volume, or when the volumes'
    chapter ranges interleave (volume metadata too inconsistent to trust).
    Volume 0 is treated as "no volume", matching the ComicInfo writer.
    """
    by_volume: dict[float, list[float]] = {}
    unvolumed: list[float] = []
    for ch in chapters:
        if ch.value is None:
            continue
        volume = safe_float(ch.volume) if ch.volume else None
        if volume is None or volume <= 0:
            unvolumed.append(ch.value)
        else:
            by_volume.setdefault(volume, []).append(ch.value)
    if not by_volume:
        return []
    ranges = [BookRange(min(vals), max(vals)) for _, vals in sorted(by_volume.items())]
    for prev, nxt in pairwise(ranges):
        if prev.end is not None and nxt.start <= prev.end:
            return []
    # Volume-less chapters between two volumes (extras, omake, x.5 chapters)
    # usually belong with the volume before them: stretch that volume's end
    # over them so they aren't left unassigned.
    for i, (prev, nxt) in enumerate(pairwise(ranges)):
        between = [v for v in unvolumed if prev.end is not None and prev.end < v < nxt.start]
        if between:
            ranges[i] = BookRange(prev.start, max(between))
    last_end = ranges[-1].end
    tail = [v for v in unvolumed if last_end is not None and v > last_end]
    if tail:
        ranges.append(BookRange(min(tail), None))
    return ranges


@dataclass(frozen=True)
class SeriesContext:
    """Series-level metadata shared by every book of one series."""

    name: str
    url: str
    description: str = ""
    writer: str = ""
    penciller: str = ""
    publisher: str = ""
    language: str = ""
    published: str = ""
    tags: tuple[str, ...] = ()
    reading_direction: str = "ltr"


def build_series_context(
    *,
    name: str,
    url: str,
    series_json: dict[str, Any],
    chapters: Sequence[DiskChapter],
    target_tags: Sequence[str],
    target_reading_direction: str | None,
    default_reading_direction: str,
) -> SeriesContext:
    """Merge the per-target settings, the series.json the packer maintains,
    and the chapters' ComicInfo into one SeriesContext.

    Precedence per field: the target row (tags, reading direction) beats
    series.json, which beats the first chapter that carries a value.
    """

    def from_json(key: str) -> str:
        value = series_json.get(key)
        return value.strip() if isinstance(value, str) else ""

    def from_chapters(attr: str) -> str:
        for ch in chapters:
            value = getattr(ch, attr)
            if value:
                return value
        return ""

    json_tags = series_json.get("tags")
    tags = list(target_tags) or (
        [t for t in json_tags if isinstance(t, str)] if isinstance(json_tags, list) else []
    )
    direction = (
        target_reading_direction or from_json("reading_direction") or default_reading_direction
    )
    return SeriesContext(
        name=name,
        url=url,
        description=from_json("description_text") or from_chapters("summary"),
        writer=from_json("writer") or from_chapters("writer"),
        penciller=from_json("penciller") or from_chapters("penciller"),
        publisher=from_json("publisher"),
        language=from_json("language") or from_chapters("language"),
        published=from_json("publication_date"),
        tags=tuple(normalize_tags(tags)),
        reading_direction=normalize_reading_direction(direction),
    )


def default_book_title(series: str, position: int) -> str:
    return f"{series}, Vol. {position}" if series else f"Vol. {position}"


def book_file_path(export_dir: Path, series: str, position: int) -> Path:
    """`<export dir>/<Series>/<Series> - Vol. NN.epub` — keyed by position, not
    title, so renaming a book re-exports over the same file."""
    series_part = sanitize(series)
    return export_dir / series_part / f"{series_part} - Vol. {position:02d}.epub"


def _people(*values: str) -> tuple[str, ...]:
    """Split comma-joined name lists (how the packer stores multiple authors)
    and dedupe case-insensitively, keeping first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        for name in clean_person_names(value).split(","):
            cleaned = name.strip()
            if cleaned and cleaned.casefold() not in seen:
                seen.add(cleaned.casefold())
                out.append(cleaned)
    return tuple(out)


def book_metadata(
    ctx: SeriesContext, position: int, title: str, chapters: Sequence[DiskChapter]
) -> EpubMetadata:
    first, last = chapters[0], chapters[-1]
    if first is last:
        span = f"Chapter {first.number}."
    else:
        span = f"Chapters {first.number}–{last.number}."  # noqa: RUF001 — en dash is intended
    description = f"{ctx.description}\n\n{span}" if ctx.description else span
    return EpubMetadata(
        # Stable per (series URL, book position) so a re-export after new
        # chapters arrive is recognised as the same book by readers.
        identifier=f"urn:uuid:{uuid5(NAMESPACE_URL, f'{ctx.url}#epub-book-{position}')}",
        title=title,
        series=ctx.name,
        series_index=position,
        language=ctx.language or "und",
        authors=_people(ctx.writer, ctx.penciller),
        publisher=ctx.publisher,
        description=description,
        # A book was first published when its earliest chapter was.
        published=earliest_date(ch.date for ch in chapters) or ctx.published,
        tags=ctx.tags,
        source_url=ctx.url,
        reading_direction=ctx.reading_direction,
    )


def book_chapters(chapters: Sequence[DiskChapter]) -> list[EpubChapter]:
    return [EpubChapter(number=ch.number, title=ch.title, cbz_path=ch.path) for ch in chapters]


def book_fingerprint(meta: EpubMetadata, chapters: Sequence[DiskChapter]) -> str:
    """Hash of everything that determines the built file's content.

    Archive size + mtime stand in for the page bytes; the chapter labels
    cover the TOC.
    """
    payload = {
        "v": BUILD_FORMAT_VERSION,
        "meta": dataclasses.asdict(meta),
        "chapters": [
            [ch.path.name, ch.size, ch.mtime_ns, chapter_label(ch.number, ch.title)]
            for ch in chapters
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BookPlan:
    """A stored book resolved against the chapters currently on disk."""

    book_id: int
    position: int
    title: str
    custom_title: str | None
    range: BookRange
    chapters: list[DiskChapter]
    status: BookStatus
    path: Path
    meta: EpubMetadata | None
    fingerprint: str | None
    export_path: str | None
    exported_at: str | None
    # The last exported file is still on disk (and so downloadable), whatever
    # the status says about its freshness.
    file_exists: bool


@dataclass(frozen=True)
class StoredBook:
    """The subset of an `epub_books` row planning needs (keeps this module
    free of the DB/schema layer)."""

    id: int
    position: int
    title: str | None
    chapter_start: float
    chapter_end: float | None
    export_path: str | None
    export_fingerprint: str | None
    exported_at: str | None


def plan_books(
    ctx: SeriesContext | None,
    books: Sequence[StoredBook],
    chapters: Sequence[DiskChapter],
    export_dir: Path,
) -> list[BookPlan]:
    """Resolve each stored book to its chapters, metadata and export status.

    `ctx` is None when the series has no name yet (never downloaded); every
    book then plans as empty.
    """
    plans: list[BookPlan] = []
    for book in sorted(books, key=lambda b: b.position):
        rng = BookRange(book.chapter_start, book.chapter_end)
        series = ctx.name if ctx is not None else ""
        title = book.title or default_book_title(series, book.position)
        path = book_file_path(export_dir, series or "_", book.position)
        in_book = [ch for ch in chapters if rng.contains(ch.value)] if ctx is not None else []
        meta: EpubMetadata | None = None
        fingerprint: str | None = None
        file_exists = bool(book.export_path) and Path(book.export_path or "").is_file()
        status: BookStatus
        if ctx is None or not in_book:
            status = "empty"
        else:
            meta = book_metadata(ctx, book.position, title, in_book)
            fingerprint = book_fingerprint(meta, in_book)
            if not file_exists:
                status = "not_exported"
            elif book.export_fingerprint != fingerprint or book.export_path != str(path):
                status = "outdated"
            else:
                status = "exported"
        plans.append(
            BookPlan(
                book_id=book.id,
                position=book.position,
                title=title,
                custom_title=book.title,
                range=rng,
                chapters=in_book,
                status=status,
                path=path,
                meta=meta,
                fingerprint=fingerprint,
                export_path=book.export_path,
                exported_at=book.exported_at,
                file_exists=file_exists,
            )
        )
    return plans
