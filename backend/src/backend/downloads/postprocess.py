"""Pack downloaded manga chapter directories into CBZ archives with ComicInfo.xml.

Records are produced by `_ProgressDownloadJob` in `gallery.py` as files complete;
this module groups them into chapters and packs each into a Komga-compatible CBZ
at `<output_dir>/<series>/<chapter-name>.cbz` (chapter name from config template).
A Mylar-style `series.json` is written next to each series so Komga can import
series-level metadata (description, authors, tags, reading direction).

The metadata primitives (kwdict coercion, ComicInfo/series.json construction,
naming template) live in `backend.comic_metadata`; the library-wide rename and
regen maintenance routines live in `backend.maintenance.library_ops`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from backend.app_config.constants import DEFAULT_CHAPTER_NAMING_TEMPLATE
from backend.comic_metadata import (
    IMAGE_SUFFIXES,
    ChapterRecord,
    FileRecord,
    SeriesMetadata,
    build_comicinfo_xml,
    derive_series_metadata,
    format_chapter_number,
    numbered_cbz_candidates,
    render_chapter_stem,
    safe_float,
    sanitize,
    write_series_json,
)

logger = logging.getLogger(__name__)


@dataclass
class PostResult:
    total: int
    succeeded: int
    failed: int
    error_summary: str | None = None


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
                status=rec.status,
            )
            by_dir[d] = ch
        if rec.path.suffix.lower() in IMAGE_SUFFIXES:
            ch.pages.append(rec.path)
    for ch in by_dir.values():
        ch.pages.sort()
    return sorted(by_dir.values(), key=_chapter_sort_key)


def _chapter_sort_key(ch: ChapterRecord) -> tuple[int, float, str]:
    try:
        vol = int(ch.volume) if ch.volume else 0
    except ValueError:
        vol = 0
    cnum = safe_float(ch.chapter)
    return (vol, cnum if cnum is not None else 0.0, ch.chapter)


def cbz_target_path(
    output_dir: Path, ch: ChapterRecord, naming_template: str = DEFAULT_CHAPTER_NAMING_TEMPLATE
) -> Path:
    series = sanitize(ch.manga)
    stem = render_chapter_stem(ch, naming_template)
    for candidate in numbered_cbz_candidates(output_dir / series, stem):
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many CBZ collisions for {stem!r} under {output_dir / series}")


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


@dataclass
class PackedChapterIndex:
    """Chapters already packed as CBZs in one series directory.

    Built with a single directory scan (`build_packed_chapter_index`) so each
    membership check is a set lookup. Chapter numbers from a readable
    ComicInfo.xml are indexed both as floats (so "1.0" matches "1") and as
    stripped strings (for non-numeric chapters); archives without usable
    ComicInfo fall back to the `<series> - c<chapter>` stem token.
    """

    floats: set[float] = field(default_factory=set)
    strings: set[str] = field(default_factory=set)
    stem_tokens: set[str] = field(default_factory=set)

    def contains(self, chapter: str) -> bool:
        if not chapter:
            return False
        value = safe_float(chapter)
        if value is not None and value in self.floats:
            return True
        if chapter.strip() in self.strings:
            return True
        return format_chapter_number(chapter) in self.stem_tokens


def build_packed_chapter_index(output_dir: Path, manga: str) -> PackedChapterIndex:
    """Scan `<output_dir>/<series>` once and index every packed chapter.

    Matches the cbz_target_path stem pattern so re-pack variants ("(1)") and
    title-bearing variants ("- Title") all count as already-packed. The
    directory is read in one pass — callers checking many chapters against a
    large series (the watched-target skip filter) must not pay a full rescan
    per chapter, especially on a network mount.
    """
    index = PackedChapterIndex()
    if not manga:
        return index
    series = sanitize(manga)
    series_dir = output_dir / series
    stem_prefix = f"{series} - c"
    try:
        children = list(series_dir.iterdir())
    except FileNotFoundError, NotADirectoryError:
        return index
    for child in children:
        if not child.is_file() or child.suffix.lower() != ".cbz":
            continue
        existing_series, existing_chapter = _read_cbz_series_chapter(child)
        if existing_series is not None and existing_chapter is not None:
            if sanitize(existing_series) != series:
                continue
            value = safe_float(existing_chapter)
            if value is not None:
                index.floats.add(value)
            index.strings.add(existing_chapter.strip())
            continue
        stem = child.stem
        if stem.startswith(stem_prefix):
            # Token up to the first space — covers the bare stem, the
            # collision "(1)" variant, and the "- Title" variant alike.
            token = stem[len(stem_prefix) :].split(" ", 1)[0]
            if token:
                index.stem_tokens.add(token)
    return index


def chapter_already_packed(output_dir: Path, manga: str, chapter: str) -> bool:
    """True if a CBZ for this chapter exists under output_dir.

    One-shot convenience over `build_packed_chapter_index` — callers checking
    many chapters should build the index once and use `contains`.
    """
    if not manga or not chapter:
        return False
    return build_packed_chapter_index(output_dir, manga).contains(chapter)


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
        replace(ch, pages=pages),
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


def _is_under(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _reserve_target_path(
    output_dir: Path,
    ch: ChapterRecord,
    naming_template: str,
    reserved: set[Path],
) -> Path:
    """Pick a CBZ target that's free on disk AND not already reserved this run.

    Two chapters that resolve to the same stem (e.g. duplicate chapter numbers
    from a re-uploaded series) would race for the same file when packed in
    parallel. Reserving as we go means each chapter gets a distinct path —
    the `(1)`-suffixed variant slots in just like the sequential code would
    have produced.
    """
    series = sanitize(ch.manga)
    stem = render_chapter_stem(ch, naming_template)
    for candidate in numbered_cbz_candidates(output_dir / series, stem):
        if not candidate.exists() and candidate not in reserved:
            return candidate
    raise RuntimeError(f"too many CBZ collisions for {stem!r} under {output_dir / series}")


async def run(
    records: list[FileRecord],
    output_dir: Path,
    downloads_dir: Path,
    delete_raw: bool,
    naming_template: str = DEFAULT_CHAPTER_NAMING_TEMPLATE,
    metadata_overrides: SeriesMetadata | None = None,
    max_parallel: int = 1,
    on_chapter_done: Callable[[str, bool], None] | None = None,
) -> PostResult:
    """Pack every eligible chapter into a CBZ under `output_dir`.

    When `metadata_overrides` is supplied, its `tags` and `reading_direction`
    are baked into every per-chapter ComicInfo.xml, and a series.json is
    written under each series subdir so Komga can ingest the description,
    authors, and reading direction.

    `max_parallel` controls how many chapters are packed concurrently. Each
    pack runs on a thread (zipfile releases the GIL during deflate), so a few
    threads overlap CPU-bound deflate with the shutil.rmtree on the previous
    chapter. Target paths are reserved sequentially before packing kicks off
    so two chapters that resolve to the same stem don't race to the same file.
    """
    chapters = collect_chapters(records)
    if not chapters:
        return PostResult(total=0, succeeded=0, failed=0)

    total = len(chapters)
    series_meta = derive_series_metadata(chapters, metadata_overrides)
    reading_direction = series_meta.reading_direction
    tags = series_meta.tags

    # Reserve target paths up front, sequentially — `cbz_target_path` checks
    # `exists()` on disk, so two parallel packers could otherwise both land on
    # `S - c001.cbz`.
    pack_items: list[tuple[ChapterRecord, Path]] = []
    reserved: set[Path] = set()
    for ch in chapters:
        if not ch.dir.exists():
            continue
        target = _reserve_target_path(output_dir, ch, naming_template, reserved)
        reserved.add(target)
        pack_items.append((ch, target))

    sem = asyncio.Semaphore(max(1, max_parallel))

    async def pack(ch: ChapterRecord, target: Path) -> tuple[ChapterRecord, Path, Exception | None]:
        async with sem:
            try:
                await asyncio.to_thread(
                    _pack_chapter_sync,
                    ch,
                    target,
                    downloads_dir,
                    delete_raw,
                    reading_direction,
                    tags,
                )
                return ch, target, None
            except Exception as exc:
                logger.exception("postprocess chapter failed: c=%s", ch.chapter)
                return ch, target, exc

    results = await asyncio.gather(*(pack(ch, t) for ch, t in pack_items))

    failures: list[tuple[ChapterRecord, str]] = []
    succeeded = 0
    chapters_by_series: dict[Path, list[ChapterRecord]] = {}
    for ch, target, exc in results:
        if exc is None:
            succeeded += 1
            chapters_by_series.setdefault(target.parent, []).append(ch)
        else:
            failures.append((ch, str(exc)))
        if on_chapter_done is not None:
            try:
                on_chapter_done(ch.chapter, exc is None)
            except Exception:
                logger.exception("on_chapter_done callback raised")

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
