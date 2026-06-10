"""Reconcile a download's needed chapters + emitted FileRecords + captured
per-chapter errors into a persistable per-chapter outcome list.

Pure functions only — no DB, no gallery-dl. Tested in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from backend.comic_metadata import IMAGE_SUFFIXES, FileRecord

# reconcile_outcomes only ever emits the first three; "pending" is the
# persisted state of a not-yet-reconciled manifest row (and legacy NULL rows),
# surfaced when reading outcomes back out of the DB.
ChapterOutcomeStatus = Literal["downloaded", "skipped", "failed", "pending"]


@dataclass(frozen=True)
class ChapterSeed:
    """A needed chapter discovered by the metadata pass."""

    name: str
    date: str


@dataclass(frozen=True)
class ChapterOutcome:
    name: str
    status: ChapterOutcomeStatus
    pages: int
    title: str
    date: str
    error: str | None


def _pages(records: list[FileRecord]) -> int:
    return sum(1 for r in records if r.path.suffix.lower() in IMAGE_SUFFIXES)


def _first(values: Iterable[str], fallback: str = "") -> str:
    return next((v for v in values if v), fallback)


def _downloaded(name: str, recs: list[FileRecord], date_fallback: str = "") -> ChapterOutcome:
    """Build a `downloaded` outcome from the records keyed to one chapter."""
    return ChapterOutcome(
        name=name,
        status="downloaded",
        pages=_pages(recs),
        title=_first(r.title for r in recs),
        date=_first((r.date for r in recs), date_fallback),
        error=None,
    )


def reconcile_outcomes(
    needed: list[ChapterSeed],
    records: list[FileRecord],
    chapter_errors: dict[str, str],
    exit_code: int,
) -> list[ChapterOutcome]:
    """Map each needed chapter (and any unlisted-but-downloaded chapter) to a
    concrete outcome.

    - records present  -> downloaded (pages/title/date from records)
    - error captured   -> failed (with reason)
    - clean exit, none -> skipped (gallery-dl archive already had the files)
    - dirty exit, none -> failed (reason unknown)
    Chapters that produced records but weren't in `needed` (date-less
    extractors) are appended as downloaded so the trace isn't blank.
    """
    by_chapter: dict[str, list[FileRecord]] = {}
    for r in records:
        if r.chapter:
            by_chapter.setdefault(r.chapter, []).append(r)

    out: list[ChapterOutcome] = []
    for seed in needed:
        recs = by_chapter.get(seed.name)
        if recs:
            out.append(_downloaded(seed.name, recs, seed.date))
        elif seed.name in chapter_errors:
            out.append(
                ChapterOutcome(seed.name, "failed", 0, "", seed.date, chapter_errors[seed.name])
            )
        elif exit_code == 0:
            out.append(ChapterOutcome(seed.name, "skipped", 0, "", seed.date, None))
        else:
            out.append(ChapterOutcome(seed.name, "failed", 0, "", seed.date, None))

    needed_names = {s.name for s in needed}
    for chapter, recs in by_chapter.items():
        if chapter in needed_names:
            continue
        out.append(_downloaded(chapter, recs))
    return out
