"""Comic/manga metadata primitives shared by downloads and maintenance.

Pure helpers with no app state: kwdict coercion (gallery-dl's metadata
dicts vary wildly between extractors), filename sanitisation, the chapter
naming template, ComicInfo.xml construction, and the Mylar-style
series.json that Komga imports for series-level metadata.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, Template
from jinja2.sandbox import SandboxedEnvironment

from backend.app_config.constants import (
    DEFAULT_READING_DIRECTION,
    READING_DIRECTIONS,
)

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
    status: str = ""


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
    status: str = ""


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


# Four-state local labels surfaced in the UI / persisted on each target.
# Keep this set in sync with the SERIES_STATUS_OPTIONS list in the frontend.
# Komga's series.json importer only understands a two-state subset
# (see `MYLAR_STATUS_BY_LOCAL` below); Hiatus/Abandoned are pushed via the
# REST `push_komga_series_status` maintenance job in `maintenance/komga.py`.
SERIES_STATUSES: tuple[str, ...] = ("Ongoing", "Ended", "Hiatus", "Abandoned")

# Komga's `MylarSeriesProvider` only matches two literal status strings:
# `Continuing` → ONGOING and `Ended` → ENDED. Anything else (including
# `Ongoing`, `Hiatus`, `Abandoned`) is silently ignored on import, which is
# why every series ends up looking ONGOING by default if we write our local
# labels verbatim. Translate to the wire subset before serialising; the
# unmapped states are omitted from series.json entirely and handled by the
# REST push instead.
MYLAR_STATUS_BY_LOCAL: dict[str, str] = {
    "Ongoing": "Continuing",
    "Ended": "Ended",
}

# Synonyms that manga extractors (mangadex, manganelo, mangafire, kaliscan…)
# surface via the `status` kwdict field, normalised to the Komga set above.
# Keys are matched after lowercasing + whitespace collapse, so capitalisation
# and separator (`-` / `_` / ` `) variants don't need their own entries.
_STATUS_SYNONYMS: dict[str, str] = {
    "ongoing": "Ongoing",
    "publishing": "Ongoing",
    "serializing": "Ongoing",
    "active": "Ongoing",
    "in progress": "Ongoing",
    "completed": "Ended",
    "complete": "Ended",
    "finished": "Ended",
    "ended": "Ended",
    "hiatus": "Hiatus",
    "on hiatus": "Hiatus",
    "paused": "Hiatus",
    "on hold": "Hiatus",
    "abandoned": "Abandoned",
    "cancelled": "Abandoned",
    "canceled": "Abandoned",
    "discontinued": "Abandoned",
    "dropped": "Abandoned",
}


def normalize_series_status(value: str | None) -> str:
    """Map an arbitrary publication-status string to a Komga-compatible label.

    Returns one of `SERIES_STATUSES` or an empty string when the input is blank
    or doesn't match any known synonym. The empty-string sentinel mirrors the
    rest of `SeriesMetadata` — empty values are dropped from the on-disk
    series.json rather than written as null/blank fields.
    """
    if not value:
        return ""
    if value in SERIES_STATUSES:
        return value
    key = " ".join(value.replace("_", " ").replace("-", " ").lower().split())
    return _STATUS_SYNONYMS.get(key, "")


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
            if len(cleaned) >= 2 and cleaned.startswith(open_c) and cleaned.endswith(close_c):
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


def date_iso(value: Any) -> str:
    """Coerce a gallery-dl `date` kwdict value to a YYYY-MM-DD string.

    Extractors variously expose the chapter publication timestamp as a
    `datetime` (parsed via gallery-dl's helpers) or as a pre-formatted string.
    Anything else round-trips through `str(value)` — same fallback as the
    rest of the kwdict-coercion helpers.
    """
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
        date=date_iso(kwdict.get("date")),
        path=full_path,
        description=description,
        artist=_author_name(kwdict.get("artist")),
        status=normalize_series_status(_first_str(kwdict, ("status", "publication_status"))),
    )


def safe_float(value: str) -> float | None:
    """float() that returns None on conversion failure instead of raising."""
    try:
        return float(value)
    except ValueError:
        return None


_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize(name: str) -> str:
    cleaned = _ILLEGAL.sub("_", name).strip()
    while cleaned.endswith("."):
        cleaned = cleaned[:-1].rstrip()
    return cleaned or "_"


def format_chapter_number(chapter: str) -> str:
    """Format chapter for filename: zero-pad to 3 digits when integer < 1000."""
    f = safe_float(chapter)
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


@lru_cache(maxsize=64)
def _compiled_template(template: str) -> Template:
    # The naming template is rendered once per chapter; compiling it per
    # render made a large pack O(chapters) template compiles for one string.
    return _TEMPLATE_ENV.from_string(template)


def render_chapter_stem(ch: ChapterRecord, template: str) -> str:
    rendered = _compiled_template(template).render(
        manga=ch.manga,
        series=ch.manga,
        chapter=ch.chapter,
        chapter_number=format_chapter_number(ch.chapter),
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
    render_chapter_stem(sample, template)


def numbered_cbz_candidates(directory: Path, stem: str) -> Iterator[Path]:
    """Yield `<stem>.cbz` then the collision variants `<stem> (1..999).cbz`.

    Single home for the collision-suffix scheme so packing, target
    reservation, and the rename maintenance job can't drift apart.
    """
    yield directory / f"{stem}.cbz"
    for i in range(1, 1000):
        yield directory / f"{stem} ({i}).cbz"


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


def chapter_from_comicinfo(path: Path, root: ET.Element) -> ChapterRecord:
    """Rebuild a ChapterRecord from a parsed ComicInfo.xml (regen/rename jobs)."""
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
        "status": MYLAR_STATUS_BY_LOCAL.get(meta.status),
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
        if not base.status and ch.status:
            base.status = ch.status
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
