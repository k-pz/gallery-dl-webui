"""Database operations on the `series_stats` table."""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from backend.database import now_iso, transaction
from backend.epub.state import SeriesState


@dataclass(frozen=True)
class SeriesStats:
    # Packed chapter archives of the series on disk.
    chapter_count: int
    # EPUB books defined for the series.
    epub_book_count: int
    # Books never exported, or whose export is outdated.
    epub_pending_count: int


def stats_from_state(state: SeriesState) -> SeriesStats:
    return SeriesStats(
        chapter_count=len(state.chapters),
        epub_book_count=len(state.plans),
        epub_pending_count=sum(
            1 for plan in state.plans if plan.status in ("not_exported", "outdated")
        ),
    )


async def get(db: aiosqlite.Connection, target_id: int) -> SeriesStats | None:
    async with db.execute(
        "SELECT chapter_count, epub_book_count, epub_pending_count "
        "FROM series_stats WHERE target_id = ?",
        (target_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return SeriesStats(
        chapter_count=row["chapter_count"],
        epub_book_count=row["epub_book_count"],
        epub_pending_count=row["epub_pending_count"],
    )


async def save(db: aiosqlite.Connection, target_id: int, stats: SeriesStats) -> bool:
    """Store a series' stats; returns True when they differ from what was stored."""
    if await get(db, target_id) == stats:
        return False
    async with transaction(db):
        # The target may have been deleted while its directory was scanned.
        async with db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)) as cur:
            if await cur.fetchone() is None:
                return False
        await db.execute(
            "INSERT INTO series_stats(target_id, chapter_count, epub_book_count, "
            "epub_pending_count, scanned_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(target_id) DO UPDATE SET chapter_count = excluded.chapter_count, "
            "epub_book_count = excluded.epub_book_count, "
            "epub_pending_count = excluded.epub_pending_count, scanned_at = excluded.scanned_at",
            (
                target_id,
                stats.chapter_count,
                stats.epub_book_count,
                stats.epub_pending_count,
                now_iso(),
            ),
        )
    return True
