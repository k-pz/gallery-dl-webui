"""Pack downloaded manga chapter directories into CBZ archives with ComicInfo.xml.

Records are produced by `_ProgressDownloadJob` in `gallery.py` as files complete;
this module groups them into chapters and packs each into a Komga-compatible CBZ
at `<output_dir>/<series>/<chapter-name>.cbz` (chapter name from config template).
A Mylar-style `series.json` is written next to each series so Komga can import
series-level metadata (description, authors, tags, reading direction).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
    DEFAULT_READING_DIRECTION,
    READING_DIRECTIONS,
)

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".avif",
}


@dataclass
class FileRecord:
    category: str
    manga: str
    chapter: str
    title: str
    volume: str
    lang: str
    author: str
    date: str
    path: Path
    description: str = ""
    artist: str = ""


@dataclass
class ChapterRecord:
    manga: str
    chapter: str
    title: str
    volume: str
    lang: str
    author: str
    date: str
    dir: Path
    pages: list[Path] = field(default_factory=list)
    description: str = ""
    artist: str = ""


@dataclass
class PostResult:
    total: int
    succeeded: int
    failed: int
    error_summary: str | None = None


@dataclass
class SeriesMetadata:
    """User-supplied + extractor-derived series-level metadata.

    Threaded through postprocessing so the per-chapter ComicInfo and the
    per-series series.json end up with consistent values. `tags` and
    `reading_direction` are user-supplied (defaults pulled from config);
    description, authors, etc. come from gallery-dl when available.
    """

    name: str = ""
    description: str = ""
    author: str = ""
    artist: str = ""
    publisher: str = ""
    language: str = ""
    year: int | None = None
    status: str = ""
    tags: list[str] = field(default_factory=list)
    reading_direction: str = DEFAULT_READING_DIRECTION


def normalize_reading_direction(value: str | None) -> str:
    """Coerce arbitrary input to one of the known reading-direction tokens."""
    if value is None:
        return DEFAULT_READING_DIRECTION
    cleaned = value.strip().lower()
    if cleaned in READING_DIRECTIONS:
        return cleaned
    return DEFAULT_READING_DIRECTION


def normalize_tags(value: list[str] | None) -> list[str]:
    """Strip enclosing brackets/quotes/whitespace from each tag; drop blanks."""
    if not value:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        cleaned = strip_enclosing_brackets(raw)
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        out.append(cleaned)
    return out


def _str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


# Pairs of enclosing characters we strip from author/title-ish values. Many
# manga extractors surface authors as `[Studio]` or `"Author Name"` because the
# source page formats them that way; we want the bare name on metadata.
# Typographic quotes (curly single/double, Japanese brackets) are kept here on
# purpose — many sources use them; the ambiguous-character lint warning is
# silenced because matching them is the whole point of this table.
_ENCLOSING_PAIRS = (
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
    ("<", ">"),
    ("「", "」"),  # Japanese corner brackets
    ("『", "』"),  # Japanese white corner brackets
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),  # double curly quotes
    ("‘", "’"),  # single curly quotes  # noqa: RUF001
)


def strip_enclosing_brackets(value: str) -> str:
    """Remove a matching pair of enclosing brackets/quotes from a string.

    Repeats until no more matching pairs are found (handles `"[Author]"`).
    """
    cleaned = value.strip()
    while True:
        for open_c, close_c in _ENCLOSING_PAIRS:
            if (
                len(cleaned) >= 2
                and cleaned.startswith(open_c)
                and cleaned.endswith(close_c)
            ):
                cleaned = cleaned[len(open_c) : -len(close_c)].strip()
                break
        else:
            return cleaned


def _author_name(value: Any) -> str:
    # gallery-dl extractors variously expose `author` as a string or a dict
    # with a `name` key (and sometimes other keys).
    if isinstance(value, dict):
        raw = _str(value.get("name", ""))
    else:
        raw = _str(value)
    return strip_enclosing_brackets(raw)


def _date_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return _str(value)


def chapter_with_minor(kwdict: dict[str, Any]) -> str:
    """gallery-dl splits fractional chapter numbers — e.g. "700.5" arrives as
    chapter=700 + chapter_minor=".5". Re-join them so downstream naming keeps
    the decimal suffix.
    """
    chapter = _str(kwdict.get("chapter"))
    minor = _str(kwdict.get("chapter_minor"))
    if minor and not chapter.endswith(minor):
        return chapter + minor
    return chapter


def _first_str(kwdict: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = kwdict.get(key)
        s = _str(value).strip()
        if s:
            return s
    return ""


def coerce_record_from_kwdict(kwdict: dict[str, Any], full_path: Path) -> FileRecord:
    """Snapshot the metadata fields we need from a gallery-dl kwdict.

    gallery-dl mutates kwdict during the download lifecycle, so callers should
    invoke this immediately after the relevant `handle_url` step.
    """
    description = _first_str(kwdict, ("description", "summary", "abstract"))
    return FileRecord(
        category=_str(kwdict.get("category")),
        manga=_str(kwdict.get("manga")),
        chapter=chapter_with_minor(kwdict),
        title=_str(kwdict.get("title")),
        volume=_str(kwdict.get("volume")),
        lang=_str(kwdict.get("lang")),
        author=_author_name(kwdict.get("author")),
        date=_date_iso(kwdict.get("date")),
        path=full_path,
        description=description,
        artist=_author_name(kwdict.get("artist")),
    )


def collect_chapters(records: list[FileRecord]) -> list[ChapterRecord]:
    """Group records by parent dir. Records lacking manga or chapter are dropped."""
    by_dir: dict[Path, ChapterRecord] = {}
    for rec in records:
        if not rec.manga or not rec.chapter:
            continue
        d = rec.path.parent
        ch = by_dir.get(d)
        if ch is None:
            ch = ChapterRecord(
                manga=rec.manga,
                chapter=rec.chapter,
                title=rec.title,
                volume=rec.volume,
                lang=rec.lang,
                author=rec.author,
                date=rec.date,
                dir=d,
                description=rec.description,
                artist=rec.artist,
            )
            by_dir[d] = ch
        if rec.path.suffix.lower() in IMAGE_SUFFIXES:
            ch.pages.append(rec.path)
    for ch in by_dir.values():
        ch.pages.sort()
    return sorted(by_dir.values(), key=_chapter_sort_key)


def _safe_float(value: str) -> float | None:
    """float() that returns None on conversion failure instead of raising."""
    try:
        return float(value)
    except ValueError:
        return None


def _chapter_sort_key(ch: ChapterRecord) -> tuple[int, float, str]:
    try:
        vol = int(ch.volume) if ch.volume else 0
    except ValueError:
        vol = 0
    cnum = _safe_float(ch.chapter)
    return (vol, cnum if cnum is not None else 0.0, ch.chapter)


_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize(name: str) -> str:
    cleaned = _ILLEGAL.sub("_", name).strip()
    while cleaned.endswith("."):
        cleaned = cleaned[:-1].rstrip()
    return cleaned or "_"


def _format_chapter_number(chapter: str) -> str:
    """Format chapter for filename: zero-pad to 3 digits when integer < 1000."""
    f = _safe_float(chapter)
    if f is None:
        return sanitize(chapter)
    if f.is_integer() and 0 <= f < 1000:
        return f"{int(f):03d}"
    if f.is_integer():
        return str(int(f))
    whole = int(f)
    frac = chapter.split(".", 1)[1] if "." in chapter else ""
    if 0 <= whole < 1000 and frac:
        return f"{whole:03d}.{frac}"
    return sanitize(chapter)


_TEMPLATE_ENV = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined)


def _render_chapter_stem(ch: ChapterRecord, template: str) -> str:
    t = _TEMPLATE_ENV.from_string(template)
    rendered = t.render(
        manga=ch.manga,
        series=ch.manga,
        chapter=ch.chapter,
        chapter_number=_format_chapter_number(ch.chapter),
        title=ch.title,
        volume=ch.volume,
        lang=ch.lang,
        author=ch.author,
        date=ch.date,
    )
    stem = sanitize(rendered)
    if stem == "_":
        raise ValueError("chapter_naming_template rendered an empty/invalid filename")
    return stem


def render_chapter_stem(ch: ChapterRecord, template: str) -> str:
    return _render_chapter_stem(ch, template)


def validate_chapter_naming_template(template: str) -> None:
    sample = ChapterRecord(
        manga="Series",
        chapter="1",
        title="Title",
        volume="1",
        lang="en",
        author="Author",
        date="2024-01-01",
        dir=Path("."),
    )
    _render_chapter_stem(sample, template)


def cbz_target_path(
    output_dir: Path, ch: ChapterRecord, naming_template: str = DEFAULT_CHAPTER_NAMING_TEMPLATE
) -> Path:
    series = sanitize(ch.manga)
    stem = _render_chapter_stem(ch, naming_template)
    base = output_dir / series / f"{stem}.cbz"
    if not base.exists():
        return base
    for i in range(1, 1000):
        candidate = output_dir / series / f"{stem} ({i}).cbz"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many CBZ collisions at {base}")


def _chapter_matches(existing: str, incoming: str) -> bool:
    ev = _safe_float(existing)
    iv = _safe_float(incoming)
    if ev is not None and iv is not None:
        return ev == iv
    return existing.strip() == incoming.strip()


def _read_cbz_series_chapter(path: Path) -> tuple[str | None, str | None]:
    try:
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("ComicInfo.xml")
    except OSError, zipfile.BadZipFile, KeyError:
        return None, None
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None, None
    series = root.findtext("Series")
    chapter = root.findtext("Number")
    return series, chapter


def chapter_already_packed(output_dir: Path, manga: str, chapter: str) -> bool:
    """True if a CBZ for this chapter exists under output_dir.

    Matches the cbz_target_path stem pattern so re-pack variants ("(1)") and
    title-bearing variants ("- Title") all count as already-packed.
    """
    if not manga or not chapter:
        return False
    series = sanitize(manga)
    chap = _format_chapter_number(chapter)
    series_dir = output_dir / series
    try:
        for child in series_dir.iterdir():
            if not child.is_file() or child.suffix.lower() != ".cbz":
                continue
            existing_series, existing_chapter = _read_cbz_series_chapter(child)
            if existing_series is not None and existing_chapter is not None:
                if sanitize(existing_series) == series and _chapter_matches(
                    existing_chapter, chapter
                ):
                    return True
                continue
            stem_prefix = f"{series} - c{chap}"
            stem = child.stem
            if stem == stem_prefix or stem.startswith(stem_prefix + " "):
                return True
    except FileNotFoundError, NotADirectoryError:
        return False
    return False


def _manga_element_value(reading_direction: str | None) -> str:
    """Map our reading-direction enum to a ComicInfo `Manga` element value.

    Komga reads ComicInfo's `Manga` element and maps `YesAndRightToLeft` →
    RIGHT_TO_LEFT; any other truthy value defaults to LEFT_TO_RIGHT. Vertical
    and webtoon don't have standard ComicInfo values — we keep `Yes` so the
    archive still imports cleanly and rely on `series.json` plus Komga's
    series-level setting for those directions.
    """
    if reading_direction == "rtl":
        return "YesAndRightToLeft"
    return "Yes"


def build_comicinfo_xml(
    ch: ChapterRecord, reading_direction: str | None = None, tags: list[str] | None = None
) -> bytes:
    root = ET.Element(
        "ComicInfo",
        {
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        },
    )

    def _add(tag: str, value: str | int | None) -> None:
        if value is None or value == "":
            return
        ET.SubElement(root, tag).text = str(value)

    _add("Series", ch.manga)
    if ch.title:
        _add("Title", ch.title)
    _add("Number", ch.chapter)
    if ch.volume and ch.volume not in ("0", "0.0"):
        _add("Volume", ch.volume)
    if ch.description:
        _add("Summary", ch.description)
    # Strip enclosing brackets/quotes here so values constructed directly via
    # FileRecord (e.g. extractor records that bypass coerce_record_from_kwdict,
    # or maintenance regen) still get a clean author on the way out.
    writer = strip_enclosing_brackets(ch.author) if ch.author else ""
    penciller = strip_enclosing_brackets(ch.artist) if ch.artist else writer
    if writer:
        _add("Writer", writer)
    if penciller:
        _add("Penciller", penciller)
    if ch.lang:
        _add("LanguageISO", ch.lang)
    if ch.date and len(ch.date) >= 10:
        y, m, d = ch.date[:4], ch.date[5:7], ch.date[8:10]
        if y.isdigit():
            _add("Year", int(y))
        if m.isdigit():
            _add("Month", int(m))
        if d.isdigit():
            _add("Day", int(d))
    _add("PageCount", len(ch.pages))
    _add("Manga", _manga_element_value(reading_direction))
    if reading_direction == "webtoon":
        # Some Komga deployments use `Format: Webtoon` as an additional hint.
        _add("Format", "Webtoon")
    if tags:
        _add("Tags", ", ".join(tags))

    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError, OSError:
        return False
    return True


SERIES_JSON_NAME = "series.json"
SERIES_JSON_VERSION = "1.0.2"


def build_series_json_bytes(meta: SeriesMetadata, total_issues: int | None = None) -> bytes:
    """Construct a Mylar-style series.json payload that Komga can import.

    Komga reads keys under `metadata` (per their import docs) — we emit the
    handful Komga recognises plus a `reading_direction` hint that future
    metadata pipelines can rely on. Empty values are omitted so Komga doesn't
    overwrite imported defaults with blanks.
    """
    metadata: dict[str, Any] = {
        "type": "comicSeries",
        "publisher": meta.publisher or None,
        "imprint": None,
        "name": meta.name or None,
        "comicid": None,
        "year": meta.year,
        "description_formatted": None,
        "description_text": meta.description or None,
        "volume": None,
        "booktype": "Print",
        "age_rating": None,
        "collects": None,
        "comic_image": None,
        "total_issues": total_issues,
        "publication_run": None,
        "status": meta.status or None,
        # Extension fields — non-standard, kept for round-tripping our own
        # state through the regen job and for downstream Komga config.
        "language": meta.language or None,
        "writer": meta.author or None,
        "penciller": meta.artist or meta.author or None,
        "tags": list(meta.tags) if meta.tags else None,
        "reading_direction": meta.reading_direction,
    }
    metadata = {k: v for k, v in metadata.items() if v not in (None, "")}
    payload = {"version": SERIES_JSON_VERSION, "metadata": metadata}
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_series_json(series_dir: Path, meta: SeriesMetadata, total_issues: int | None) -> Path:
    """Write `<series_dir>/series.json` atomically. Creates the directory if needed."""
    series_dir.mkdir(parents=True, exist_ok=True)
    target = series_dir / SERIES_JSON_NAME
    part = target.with_suffix(target.suffix + ".part")
    if part.exists():
        part.unlink()
    part.write_bytes(build_series_json_bytes(meta, total_issues=total_issues))
    part.replace(target)
    return target


def derive_series_metadata(
    chapters: list[ChapterRecord],
    overrides: SeriesMetadata | None = None,
) -> SeriesMetadata:
    """Combine per-chapter records with user overrides into a single SeriesMetadata.

    Overrides win for `tags`, `reading_direction`, and any explicitly-set
    string fields; everything else falls back to the first non-empty value
    seen across the chapters. Author/artist values get bracket-stripped here
    so the series.json + ComicInfo see the same clean name regardless of
    whether the FileRecord went through coerce_record_from_kwdict.
    """
    base = SeriesMetadata()
    for ch in chapters:
        if not base.name and ch.manga:
            base.name = ch.manga
        if not base.description and ch.description:
            base.description = ch.description
        if not base.author and ch.author:
            base.author = strip_enclosing_brackets(ch.author)
        if not base.artist and ch.artist:
            base.artist = strip_enclosing_brackets(ch.artist)
        if not base.language and ch.lang:
            base.language = ch.lang
        if base.year is None and ch.date and len(ch.date) >= 4 and ch.date[:4].isdigit():
            base.year = int(ch.date[:4])
    if overrides is not None:
        if overrides.name:
            base.name = overrides.name
        if overrides.description:
            base.description = overrides.description
        if overrides.author:
            base.author = overrides.author
        if overrides.artist:
            base.artist = overrides.artist
        if overrides.publisher:
            base.publisher = overrides.publisher
        if overrides.language:
            base.language = overrides.language
        if overrides.year is not None:
            base.year = overrides.year
        if overrides.status:
            base.status = overrides.status
        base.tags = normalize_tags(overrides.tags)
        base.reading_direction = normalize_reading_direction(overrides.reading_direction)
    else:
        base.reading_direction = normalize_reading_direction(base.reading_direction)
    return base


def _pack_chapter_sync(
    ch: ChapterRecord,
    target: Path,
    downloads_dir: Path,
    delete_raw: bool,
    reading_direction: str | None,
    tags: list[str] | None,
) -> None:
    """Build CBZ at <target>.part, atomic-rename, optionally remove source dir."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    if part.exists():
        part.unlink()
    # Enumerate the chapter directory rather than reuse `ch.pages`: gallery-dl
    # may rewrite a file's extension mid-download when the body's signature
    # disagrees with the URL (e.g. a `.png` URL serving JPEG bytes), so the
    # path captured at handle_url time can be stale.
    pages = sorted(
        p for p in ch.dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )
    if not pages:
        raise RuntimeError(f"no image pages found in {ch.dir}")

    ci_bytes = build_comicinfo_xml(
        ChapterRecord(
            manga=ch.manga,
            chapter=ch.chapter,
            title=ch.title,
            volume=ch.volume,
            lang=ch.lang,
            author=ch.author,
            date=ch.date,
            dir=ch.dir,
            pages=pages,
            description=ch.description,
            artist=ch.artist,
        ),
        reading_direction=reading_direction,
        tags=tags,
    )
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("ComicInfo.xml", ci_bytes)
        for page in pages:
            zf.write(page, arcname=page.name)
    part.replace(target)
    if delete_raw:
        # Guard: never rmtree outside the configured downloads root.
        if not _is_under(ch.dir, downloads_dir):
            raise RuntimeError(
                f"refusing to delete {ch.dir}: not under downloads dir {downloads_dir}"
            )
        shutil.rmtree(ch.dir, ignore_errors=False)


async def _pack_chapter(
    ch: ChapterRecord,
    target: Path,
    downloads_dir: Path,
    delete_raw: bool,
    reading_direction: str | None,
    tags: list[str] | None,
) -> Path:
    await asyncio.to_thread(
        _pack_chapter_sync, ch, target, downloads_dir, delete_raw, reading_direction, tags
    )
    return target


async def run(
    records: list[FileRecord],
    output_dir: Path,
    downloads_dir: Path,
    delete_raw: bool,
    naming_template: str = DEFAULT_CHAPTER_NAMING_TEMPLATE,
    metadata_overrides: SeriesMetadata | None = None,
) -> PostResult:
    """Pack every eligible chapter into a CBZ under `output_dir`.

    When `metadata_overrides` is supplied, its `tags` and `reading_direction`
    are baked into every per-chapter ComicInfo.xml, and a series.json is
    written under each series subdir so Komga can ingest the description,
    authors, and reading direction.
    """
    chapters = collect_chapters(records)
    if not chapters:
        return PostResult(total=0, succeeded=0, failed=0)

    total = len(chapters)
    failures: list[tuple[ChapterRecord, str]] = []
    succeeded = 0

    series_meta = derive_series_metadata(chapters, metadata_overrides)
    reading_direction = series_meta.reading_direction
    tags = series_meta.tags

    chapters_by_series: dict[Path, list[ChapterRecord]] = {}

    for ch in chapters:
        if not ch.dir.exists():
            continue
        try:
            target = cbz_target_path(output_dir, ch, naming_template=naming_template)
            await _pack_chapter(
                ch, target, downloads_dir, delete_raw, reading_direction, tags
            )
            chapters_by_series.setdefault(target.parent, []).append(ch)
            succeeded += 1
        except Exception as exc:
            failures.append((ch, str(exc)))
            logger.exception("postprocess chapter failed: c=%s", ch.chapter)

    # Best-effort: write/refresh series.json next to each affected series. We
    # do this even on partial failure so the metadata for what we did manage
    # to pack is still available to Komga.
    for series_dir, packed in chapters_by_series.items():
        try:
            await asyncio.to_thread(
                write_series_json,
                series_dir,
                series_meta,
                len(packed),
            )
        except Exception:
            logger.exception("failed to write series.json under %s", series_dir)

    if failures:
        summary = f"{len(failures)} of {total} chapter(s) failed: " + "; ".join(
            f"c{ch.chapter}: {msg}" for ch, msg in failures[:5]
        )
        if len(failures) > 5:
            summary += f"; (+{len(failures) - 5} more)"
        return PostResult(
            total=total,
            succeeded=succeeded,
            failed=len(failures),
            error_summary=summary,
        )
    return PostResult(total=total, succeeded=succeeded, failed=0)


@dataclass
class RenamePackedResult:
    total: int
    renamed: int
    skipped: int


def _chapter_from_comicinfo(path: Path, root: ET.Element) -> ChapterRecord:
    year = root.findtext("Year") or ""
    month = root.findtext("Month") or ""
    day = root.findtext("Day") or ""
    if year:
        date = f"{int(year):04d}-{int(month or 1):02d}-{int(day or 1):02d}"
    else:
        date = ""
    return ChapterRecord(
        manga=root.findtext("Series") or path.parent.name,
        chapter=root.findtext("Number") or "",
        title=root.findtext("Title") or "",
        volume=root.findtext("Volume") or "",
        lang=root.findtext("LanguageISO") or "",
        author=root.findtext("Writer") or "",
        date=date,
        dir=path.parent,
        description=root.findtext("Summary") or "",
        artist=root.findtext("Penciller") or "",
    )


class RenameProgressSink(Protocol):
    def total(self, n: int) -> None: ...
    def step(self, line: str) -> None: ...


def rename_packed_chapters(
    output_root: Path,
    naming_template: str,
    progress: RenameProgressSink | None = None,
) -> RenamePackedResult:
    cbz_paths = sorted(output_root.rglob("*.cbz"))
    if progress is not None:
        progress.total(len(cbz_paths))
    total = 0
    renamed = 0
    for cbz in cbz_paths:
        total += 1
        try:
            with zipfile.ZipFile(cbz) as zf:
                xml_bytes = zf.read("ComicInfo.xml")
            root = ET.fromstring(xml_bytes)
            ch = _chapter_from_comicinfo(cbz, root)
            stem = _render_chapter_stem(ch, naming_template)
            # Rename in place — keep each archive in its source directory.
            # Per-target output dirs can sit anywhere under output_root; moving
            # everything into <output_root>/<series>/ would erase that layout.
            desired = cbz.with_name(f"{stem}.cbz")
            if desired == cbz:
                if progress is not None:
                    progress.step(f"skip (already named): {cbz.relative_to(output_root)}")
                continue
            target = desired
            if target.exists():
                for i in range(1, 1000):
                    candidate = cbz.with_name(f"{stem} ({i}).cbz")
                    if candidate == cbz:
                        target = cbz
                        break
                    if not candidate.exists():
                        target = candidate
                        break
            if target == cbz:
                if progress is not None:
                    progress.step(f"skip (already named): {cbz.relative_to(output_root)}")
                continue
            cbz.replace(target)
            renamed += 1
            if progress is not None:
                progress.step(
                    f"renamed: {cbz.relative_to(output_root)} -> {target.relative_to(output_root)}"
                )
        except Exception as exc:
            logger.exception("failed to rename chapter archive: %s", cbz)
            if progress is not None:
                progress.step(f"failed: {cbz.relative_to(output_root)}: {exc!r}")
            continue
    return RenamePackedResult(total=total, renamed=renamed, skipped=total - renamed)


@dataclass
class RegenMetadataResult:
    series: int
    archives_updated: int
    series_json_written: int
    skipped: int
    failed: int


# What the metadata-regen job needs to know about a series, keyed by the
# canonical series name written into ComicInfo.xml. The maintenance worker
# resolves this from the targets table (matching by sanitized name).
SeriesOverrideLookup = Callable[[str], SeriesMetadata | None]


def _rewrite_cbz_metadata(
    cbz: Path,
    overrides: SeriesMetadata | None,
) -> ChapterRecord | None:
    """Rewrite a CBZ's ComicInfo.xml in place, returning the resulting chapter.

    Returns None when the archive lacks a readable ComicInfo.xml (the caller
    treats this as `skipped`). The rewrite is atomic — we build a sibling
    `.part` archive and rename it over the original on success.
    """
    try:
        with zipfile.ZipFile(cbz) as zf:
            xml_bytes = zf.read("ComicInfo.xml")
            page_names = [n for n in zf.namelist() if n != "ComicInfo.xml"]
    except OSError, zipfile.BadZipFile, KeyError:
        return None
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    ch = _chapter_from_comicinfo(cbz, root)
    # Author normalisation: strip enclosing brackets/quotes from any
    # extractor-supplied value before we re-emit it.
    ch.author = strip_enclosing_brackets(ch.author)
    ch.artist = strip_enclosing_brackets(ch.artist)
    if overrides is not None:
        if overrides.description and not ch.description:
            ch.description = overrides.description
        if overrides.author and not ch.author:
            ch.author = overrides.author
        if overrides.artist and not ch.artist:
            ch.artist = overrides.artist
    ch.pages = [Path(name) for name in page_names]
    reading_direction = overrides.reading_direction if overrides else None
    tags = overrides.tags if overrides else None
    new_xml = build_comicinfo_xml(ch, reading_direction=reading_direction, tags=tags)
    part = cbz.with_suffix(cbz.suffix + ".part")
    if part.exists():
        part.unlink()
    with zipfile.ZipFile(cbz) as src, zipfile.ZipFile(
        part, "w", zipfile.ZIP_DEFLATED, compresslevel=6
    ) as dst:
        dst.writestr("ComicInfo.xml", new_xml)
        for name in src.namelist():
            if name == "ComicInfo.xml":
                continue
            with src.open(name) as fh:
                dst.writestr(name, fh.read())
    part.replace(cbz)
    return ch


class RegenProgressSink(Protocol):
    def total(self, n: int) -> None: ...
    def step(self, line: str) -> None: ...


def regenerate_series_metadata(
    output_root: Path,
    overrides_for: SeriesOverrideLookup | None = None,
    progress: RegenProgressSink | None = None,
) -> RegenMetadataResult:
    """Walk `output_root`, rewrite ComicInfo.xml + series.json for every series.

    Each `<series_dir>` is the parent of one or more CBZs; we rewrite every
    archive (so author normalisation + reading direction + tags propagate),
    then drop a fresh series.json next to them. `overrides_for(series_name)`
    supplies user-set tags / reading direction / description on a per-series
    basis — the maintenance worker plumbs this in from the targets table.
    """
    cbz_paths = sorted(output_root.rglob("*.cbz"))
    if progress is not None:
        progress.total(len(cbz_paths))
    archives_updated = 0
    skipped = 0
    failed = 0
    series_to_chapters: dict[Path, list[ChapterRecord]] = {}
    series_to_overrides: dict[Path, SeriesMetadata | None] = {}

    for cbz in cbz_paths:
        # First read to learn the series name so the override lookup is keyed
        # by what the archive actually claims, not by its parent dir. Missing
        # or unreadable ComicInfo.xml is reported as a skip; other I/O errors
        # bubble up to the failure path below.
        try:
            with zipfile.ZipFile(cbz) as zf:
                xml_bytes = zf.read("ComicInfo.xml")
        except OSError, zipfile.BadZipFile, KeyError:
            skipped += 1
            if progress is not None:
                progress.step(f"skip (no ComicInfo): {cbz.relative_to(output_root)}")
            continue
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            skipped += 1
            if progress is not None:
                progress.step(f"skip (bad ComicInfo): {cbz.relative_to(output_root)}")
            continue
        try:
            series_name = root.findtext("Series") or cbz.parent.name
            overrides = overrides_for(series_name) if overrides_for else None
            ch = _rewrite_cbz_metadata(cbz, overrides)
            if ch is None:
                skipped += 1
                if progress is not None:
                    progress.step(f"skip (no ComicInfo): {cbz.relative_to(output_root)}")
                continue
            archives_updated += 1
            series_to_chapters.setdefault(cbz.parent, []).append(ch)
            series_to_overrides[cbz.parent] = overrides
            if progress is not None:
                progress.step(f"updated: {cbz.relative_to(output_root)}")
        except Exception as exc:
            failed += 1
            logger.exception("regen failed for %s", cbz)
            if progress is not None:
                progress.step(f"failed: {cbz.relative_to(output_root)}: {exc!r}")

    series_json_written = 0
    for series_dir, chapters in series_to_chapters.items():
        overrides = series_to_overrides.get(series_dir)
        try:
            meta = derive_series_metadata(chapters, overrides)
            write_series_json(series_dir, meta, total_issues=len(chapters))
            series_json_written += 1
            if progress is not None:
                progress.step(f"series.json: {series_dir.relative_to(output_root)}")
        except Exception as exc:
            failed += 1
            logger.exception("failed to write series.json under %s", series_dir)
            if progress is not None:
                rel = (
                    series_dir.relative_to(output_root)
                    if _is_under(series_dir, output_root)
                    else series_dir
                )
                progress.step(f"failed series.json: {rel}: {exc!r}")

    return RegenMetadataResult(
        series=len(series_to_chapters),
        archives_updated=archives_updated,
        series_json_written=series_json_written,
        skipped=skipped,
        failed=failed,
    )
