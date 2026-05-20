"""Pack downloaded manga chapter directories into CBZ archives with ComicInfo.xml.

Records are produced by `_ProgressDownloadJob` in `gallery.py` as files complete;
this module groups them into chapters and packs each into a Komga-compatible CBZ
at `<output_dir>/<series>/<chapter-name>.cbz` (chapter name from config template).
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from backend.app_config.constants import DEFAULT_CHAPTER_NAMING_TEMPLATE

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


@dataclass
class PostResult:
    total: int
    succeeded: int
    failed: int
    error_summary: str | None = None


def _str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _author_name(value: Any) -> str:
    # gallery-dl extractors variously expose `author` as a string or a dict
    # with a `name` key (and sometimes other keys).
    if isinstance(value, dict):
        return _str(value.get("name", ""))
    return _str(value)


def _date_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return _str(value)


def coerce_record_from_kwdict(kwdict: dict[str, Any], full_path: Path) -> FileRecord:
    """Snapshot the metadata fields we need from a gallery-dl kwdict.

    gallery-dl mutates kwdict during the download lifecycle, so callers should
    invoke this immediately after the relevant `handle_url` step.
    """
    return FileRecord(
        category=_str(kwdict.get("category")),
        manga=_str(kwdict.get("manga")),
        chapter=_str(kwdict.get("chapter")),
        title=_str(kwdict.get("title")),
        volume=_str(kwdict.get("volume")),
        lang=_str(kwdict.get("lang")),
        author=_author_name(kwdict.get("author")),
        date=_date_iso(kwdict.get("date")),
        path=full_path,
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


def build_comicinfo_xml(ch: ChapterRecord) -> bytes:
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
    if ch.author:
        _add("Writer", ch.author)
        _add("Penciller", ch.author)
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
    _add("Manga", "Yes")

    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError, OSError:
        return False
    return True


def _pack_chapter_sync(
    ch: ChapterRecord, target: Path, downloads_dir: Path, delete_raw: bool
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
        )
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
    ch: ChapterRecord, target: Path, downloads_dir: Path, delete_raw: bool
) -> Path:
    await asyncio.to_thread(_pack_chapter_sync, ch, target, downloads_dir, delete_raw)
    return target


async def run(
    records: list[FileRecord],
    output_dir: Path,
    downloads_dir: Path,
    delete_raw: bool,
    naming_template: str = DEFAULT_CHAPTER_NAMING_TEMPLATE,
) -> PostResult:
    """Pack every eligible chapter into a CBZ under `output_dir`."""
    chapters = collect_chapters(records)
    if not chapters:
        return PostResult(total=0, succeeded=0, failed=0)

    total = len(chapters)
    failures: list[tuple[ChapterRecord, str]] = []
    succeeded = 0

    for ch in chapters:
        if not ch.dir.exists():
            continue
        try:
            target = cbz_target_path(output_dir, ch, naming_template=naming_template)
            await _pack_chapter(ch, target, downloads_dir, delete_raw)
            succeeded += 1
        except Exception as exc:
            failures.append((ch, str(exc)))
            logger.exception("postprocess chapter failed: c=%s", ch.chapter)

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
    return ChapterRecord(
        manga=root.findtext("Series") or path.parent.name,
        chapter=root.findtext("Number") or "",
        title=root.findtext("Title") or "",
        volume=root.findtext("Volume") or "",
        lang=root.findtext("LanguageISO") or "",
        author=root.findtext("Writer") or "",
        date="",
        dir=path.parent,
    )


def rename_packed_chapters(output_root: Path, naming_template: str) -> RenamePackedResult:
    total = 0
    renamed = 0
    for cbz in output_root.rglob("*.cbz"):
        total += 1
        try:
            with zipfile.ZipFile(cbz) as zf:
                xml_bytes = zf.read("ComicInfo.xml")
            root = ET.fromstring(xml_bytes)
            ch = _chapter_from_comicinfo(cbz, root)
            series = sanitize(ch.manga)
            stem = _render_chapter_stem(ch, naming_template)
            desired = output_root / series / f"{stem}.cbz"
            if desired == cbz:
                continue
            target = desired
            if target.exists():
                for i in range(1, 1000):
                    candidate = output_root / series / f"{stem} ({i}).cbz"
                    if candidate == cbz:
                        target = cbz
                        break
                    if not candidate.exists():
                        target = candidate
                        break
            if target == cbz:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            cbz.replace(target)
            renamed += 1
        except Exception:
            logger.exception("failed to rename chapter archive: %s", cbz)
            continue
    return RenamePackedResult(total=total, renamed=renamed, skipped=total - renamed)
