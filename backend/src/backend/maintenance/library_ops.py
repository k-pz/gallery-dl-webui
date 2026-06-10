"""Library-wide CBZ maintenance routines: rename + metadata regeneration.

These walk the designated output roots on disk (often a network mount) and
are invoked by the maintenance worker on a thread. They share the comic
metadata primitives with the download-time packer but are maintenance-only —
nothing under `downloads/` depends on this module.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.comic_metadata import (
    ChapterRecord,
    SeriesMetadata,
    build_comicinfo_xml,
    chapter_from_comicinfo,
    derive_series_metadata,
    numbered_cbz_candidates,
    render_chapter_stem,
    strip_enclosing_brackets,
    write_series_json,
)

logger = logging.getLogger(__name__)


class MaintenanceCancelled(Exception):
    """Raised by a maintenance routine when its cancel-check fires.

    Carries the partial progress accumulated up to the cancel point so the
    caller can persist what actually happened before unwinding.
    """

    def __init__(self, partial: dict[str, int]) -> None:
        super().__init__("maintenance cancelled")
        self.partial = partial


class ProgressSink(Protocol):
    """Callbacks the rename/regen routines use to surface live progress."""

    def total(self, n: int) -> None: ...
    def step(self, line: str) -> None: ...


@dataclass
class RenamePackedResult:
    total: int
    renamed: int
    skipped: int


def _iter_filtered_cbzs(output_roots: Sequence[Path], exclude_dirs: list[str] | None) -> list[Path]:
    """List CBZs under each of `output_roots`, skipping any whose path contains
    a name from `exclude_dirs` (case-insensitive). The match is on directory
    *names* in the path — for example, `["#recycle"]` filters out everything
    under any `#recycle/` ancestor anywhere in the tree. Results are deduped by
    resolved path so overlapping roots don't double-process the same archive.
    """
    excluded_lower = {name.lower() for name in (exclude_dirs or []) if name}
    seen: dict[Path, Path] = {}
    for root in output_roots:
        if not root.exists() or not root.is_dir():
            continue
        for cbz in root.rglob("*.cbz"):
            if excluded_lower and any(part.lower() in excluded_lower for part in cbz.parts):
                continue
            try:
                key = cbz.resolve()
            except OSError:
                key = cbz
            seen.setdefault(key, cbz)
    return sorted(seen.values())


def _relativize(cbz: Path, roots: Sequence[Path]) -> Path:
    """Return `cbz` rendered relative to whichever of `roots` contains it.

    Falls back to the bare path so progress lines stay readable even for
    archives that don't sit cleanly under any of the supplied roots (e.g. when
    roots overlap via symlinks).
    """
    for root in roots:
        try:
            return cbz.relative_to(root)
        except ValueError:
            continue
    return cbz


def _rename_target(cbz: Path, stem: str) -> Path | None:
    """Pick where `cbz` should move for `stem`, or None when no slot is free.

    Returns `cbz` itself when the archive already sits on the stem (or one of
    its collision variants) — the caller treats that as "already named".
    """
    for candidate in numbered_cbz_candidates(cbz.parent, stem):
        if candidate == cbz:
            return cbz
        if not candidate.exists():
            return candidate
    return None


def rename_packed_chapters(
    output_roots: Sequence[Path],
    naming_template: str,
    progress: ProgressSink | None = None,
    should_cancel: Callable[[], bool] | None = None,
    exclude_dirs: list[str] | None = None,
) -> RenamePackedResult:
    cbz_paths = _iter_filtered_cbzs(output_roots, exclude_dirs)
    if progress is not None:
        progress.total(len(cbz_paths))
    total = 0
    renamed = 0
    for cbz in cbz_paths:
        if should_cancel is not None and should_cancel():
            raise MaintenanceCancelled(
                {"total": total, "renamed": renamed, "skipped": total - renamed}
            )
        total += 1
        try:
            with zipfile.ZipFile(cbz) as zf:
                xml_bytes = zf.read("ComicInfo.xml")
            root = ET.fromstring(xml_bytes)
            ch = chapter_from_comicinfo(cbz, root)
            stem = render_chapter_stem(ch, naming_template)
            # Rename in place — keep each archive in its source directory.
            # Per-target output dirs can sit anywhere under the roots; moving
            # everything into <root>/<series>/ would erase that layout.
            target = _rename_target(cbz, stem)
            if target is None:
                # Every collision slot is taken; replacing an existing archive
                # here would destroy data, so leave this one alone.
                if progress is not None:
                    progress.step(f"failed (too many collisions): {_relativize(cbz, output_roots)}")
                continue
            if target == cbz:
                if progress is not None:
                    progress.step(f"skip (already named): {_relativize(cbz, output_roots)}")
                continue
            cbz.replace(target)
            renamed += 1
            if progress is not None:
                progress.step(
                    f"renamed: {_relativize(cbz, output_roots)} -> "
                    f"{_relativize(target, output_roots)}"
                )
        except Exception as exc:
            logger.exception("failed to rename chapter archive: %s", cbz)
            if progress is not None:
                progress.step(f"failed: {_relativize(cbz, output_roots)}: {exc!r}")
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

# Optional per-chapter date override. Called as `fn(series_name, chapter)` and
# returns an ISO `YYYY-MM-DD` string when a fresh date was rediscovered from
# the upstream extractor, or `None` to leave the existing ComicInfo date alone.
ChapterDateLookup = Callable[[str, str], str | None]


_REGEN_SKIP_NONE = "no_comicinfo"
_REGEN_SKIP_BAD = "bad_comicinfo"


def _read_regen_chapter(
    cbz: Path,
    overrides_for: SeriesOverrideLookup | None,
    chapter_date_for: ChapterDateLookup | None,
) -> tuple[ChapterRecord, SeriesMetadata | None] | str:
    """Read a CBZ's ComicInfo.xml and build the regen ChapterRecord.

    Pure read — never touches the archive on disk. Returns either
    `(ChapterRecord, overrides)` on success or one of the `_REGEN_SKIP_*`
    sentinels when the archive's ComicInfo can't be loaded. The returned
    record has overrides + `chapter_date_for` already merged in so the
    caller can hand it straight to `derive_series_metadata` (for the
    series.json) and `_rewrite_regen_cbz` (for the on-disk update) without
    re-parsing.
    """
    try:
        with zipfile.ZipFile(cbz) as zf:
            xml_bytes = zf.read("ComicInfo.xml")
            page_names = [n for n in zf.namelist() if n != "ComicInfo.xml"]
    except OSError, zipfile.BadZipFile, KeyError:
        return _REGEN_SKIP_NONE
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return _REGEN_SKIP_BAD
    ch = chapter_from_comicinfo(cbz, root)
    # Author normalisation: strip enclosing brackets/quotes from any
    # extractor-supplied value before we re-emit it.
    ch.author = strip_enclosing_brackets(ch.author)
    ch.artist = strip_enclosing_brackets(ch.artist)
    series_name = root.findtext("Series") or cbz.parent.name
    overrides = overrides_for(series_name) if overrides_for else None
    if overrides is not None:
        if overrides.description and not ch.description:
            ch.description = overrides.description
        if overrides.author and not ch.author:
            ch.author = overrides.author
        if overrides.artist and not ch.artist:
            ch.artist = overrides.artist
    if chapter_date_for is not None and ch.manga and ch.chapter:
        fresh_date = chapter_date_for(ch.manga, ch.chapter)
        if fresh_date:
            ch.date = fresh_date
    ch.pages = [Path(name) for name in page_names]
    return ch, overrides


def _rewrite_regen_cbz(
    cbz: Path,
    ch: ChapterRecord,
    overrides: SeriesMetadata | None,
) -> None:
    """Rewrite the ComicInfo.xml inside `cbz` using the prepared ChapterRecord.

    Atomic: a sibling `.part` archive is built and renamed over the original
    on success. The page bytes are copied verbatim from the source archive;
    only ComicInfo.xml is replaced.
    """
    reading_direction = overrides.reading_direction if overrides else None
    tags = overrides.tags if overrides else None
    new_xml = build_comicinfo_xml(ch, reading_direction=reading_direction, tags=tags)
    part = cbz.with_suffix(cbz.suffix + ".part")
    if part.exists():
        part.unlink()
    with (
        zipfile.ZipFile(cbz) as src,
        zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as dst,
    ):
        dst.writestr("ComicInfo.xml", new_xml)
        for name in src.namelist():
            if name == "ComicInfo.xml":
                continue
            with src.open(name) as fh:
                dst.writestr(name, fh.read())
    part.replace(cbz)


def regenerate_series_metadata(
    output_roots: Sequence[Path],
    overrides_for: SeriesOverrideLookup | None = None,
    progress: ProgressSink | None = None,
    should_cancel: Callable[[], bool] | None = None,
    exclude_dirs: list[str] | None = None,
    chapter_date_for: ChapterDateLookup | None = None,
) -> RegenMetadataResult:
    """Walk each of `output_roots`, rewrite ComicInfo.xml + series.json for
    every series found within.

    Each `<series_dir>` is the parent of one or more CBZs; we rewrite every
    archive (so author normalisation + reading direction + tags propagate),
    then drop a fresh series.json next to them. `overrides_for(series_name)`
    supplies user-set tags / reading direction / description on a per-series
    basis — the maintenance worker plumbs this in from the targets table.
    `chapter_date_for(series_name, chapter)`, when supplied, lets the regen
    backfill chapter release dates rediscovered from the upstream extractor.

    The traversal runs in two phases. Phase 1 reads every CBZ's ComicInfo.xml
    so the chapter list per series is known up front; nothing is written to
    disk yet. Phase 2 walks the discovered series; for each one the fresh
    series.json is written FIRST, and only then are the per-chapter CBZs
    rewritten. Importers that mtime-watch series.json (Komga in particular)
    therefore see the series-level update before per-chapter ComicInfo
    changes start to ripple in.
    """
    cbz_paths = _iter_filtered_cbzs(output_roots, exclude_dirs)
    if progress is not None:
        progress.total(len(cbz_paths))
    archives_updated = 0
    series_json_written = 0
    skipped = 0
    failed = 0
    # series_dir -> list of (cbz_path, ChapterRecord, overrides). Built in
    # phase 1, drained in phase 2.
    series_to_entries: dict[Path, list[tuple[Path, ChapterRecord, SeriesMetadata | None]]] = {}

    def _cancelled_partial() -> dict[str, int]:
        return {
            "series": len(series_to_entries),
            "archives_updated": archives_updated,
            "series_json_written": series_json_written,
            "skipped": skipped,
            "failed": failed,
        }

    # Phase 1: read every CBZ, building per-series chapter lists. No disk
    # writes happen here — successful reads stay silent on the progress sink
    # so the matching "updated:" step from phase 2 counts the archive exactly
    # once. Skip/fail reads emit their step immediately since they're done.
    for cbz in cbz_paths:
        if should_cancel is not None and should_cancel():
            raise MaintenanceCancelled(_cancelled_partial())
        try:
            outcome = _read_regen_chapter(cbz, overrides_for, chapter_date_for)
        except Exception as exc:
            failed += 1
            logger.exception("regen read failed for %s", cbz)
            if progress is not None:
                progress.step(f"failed: {_relativize(cbz, output_roots)}: {exc!r}")
            continue
        if isinstance(outcome, str):
            skipped += 1
            if progress is not None:
                label = "no ComicInfo" if outcome == _REGEN_SKIP_NONE else "bad ComicInfo"
                progress.step(f"skip ({label}): {_relativize(cbz, output_roots)}")
            continue
        ch, overrides = outcome
        series_to_entries.setdefault(cbz.parent, []).append((cbz, ch, overrides))

    # Phase 2: per series, write series.json first then rewrite the CBZs.
    # A series.json failure does not abort the chapter rewrites — leaving the
    # per-chapter ComicInfo.xml stale on a series.json hiccup would be worse
    # than partial success.
    for series_dir, entries in series_to_entries.items():
        if should_cancel is not None and should_cancel():
            raise MaintenanceCancelled(_cancelled_partial())
        chapters = [ch for _, ch, _ in entries]
        # All entries under one series_dir share the same overrides (the
        # lookup is keyed by series name, and a directory holds exactly one
        # series), so the first entry's overrides represent the series.
        series_overrides = entries[0][2]
        try:
            meta = derive_series_metadata(chapters, series_overrides)
            write_series_json(series_dir, meta, total_issues=len(chapters))
            series_json_written += 1
            if progress is not None:
                progress.step(f"series.json: {_relativize(series_dir, output_roots)}")
        except Exception as exc:
            failed += 1
            logger.exception("failed to write series.json under %s", series_dir)
            if progress is not None:
                progress.step(
                    f"failed series.json: {_relativize(series_dir, output_roots)}: {exc!r}"
                )

        for cbz, ch, overrides in entries:
            if should_cancel is not None and should_cancel():
                raise MaintenanceCancelled(_cancelled_partial())
            try:
                _rewrite_regen_cbz(cbz, ch, overrides)
                archives_updated += 1
                if progress is not None:
                    progress.step(f"updated: {_relativize(cbz, output_roots)}")
            except Exception as exc:
                failed += 1
                logger.exception("regen failed for %s", cbz)
                if progress is not None:
                    progress.step(f"failed: {_relativize(cbz, output_roots)}: {exc!r}")

    return RegenMetadataResult(
        series=len(series_to_entries),
        archives_updated=archives_updated,
        series_json_written=series_json_written,
        skipped=skipped,
        failed=failed,
    )
