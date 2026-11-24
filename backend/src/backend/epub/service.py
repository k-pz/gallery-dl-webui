"""Database operations on the `epub_books` table."""

from __future__ import annotations

from collections.abc import Sequence

import aiosqlite

from backend.database import now_iso, transaction
from backend.epub.schemas import EpubBook


async def list_books(db: aiosqlite.Connection, target_id: int) -> list[EpubBook]:
    async with db.execute(
        "SELECT * FROM epub_books WHERE target_id = ? ORDER BY position", (target_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [EpubBook.from_row(r) for r in rows]


async def get_book(db: aiosqlite.Connection, target_id: int, book_id: int) -> EpubBook | None:
    async with db.execute(
        "SELECT * FROM epub_books WHERE id = ? AND target_id = ?", (book_id, target_id)
    ) as cur:
        row = await cur.fetchone()
    return EpubBook.from_row(row) if row else None


async def replace_books(
    db: aiosqlite.Connection,
    target_id: int,
    books: Sequence[tuple[float, str | None]],
) -> list[EpubBook]:
    """Replace a series' book list with `books` — (start chapter, title)
    pairs, already validated and sorted.

    Positions are reassigned 1..n in the given order. A new book starting at
    the same chapter as an existing one keeps that book's export record, so
    its status is recomputed against the last export (and shows as outdated
    if its chapters changed) instead of resetting to "never exported" on
    every save.
    """
    async with transaction(db):
        async with db.execute("SELECT * FROM epub_books WHERE target_id = ?", (target_id,)) as cur:
            old = [EpubBook.from_row(r) for r in await cur.fetchall()]
        by_start = {b.chapter_start: b for b in old}
        await db.execute("DELETE FROM epub_books WHERE target_id = ?", (target_id,))
        for position, (start, title) in enumerate(books, start=1):
            prev = by_start.get(start)
            await db.execute(
                "INSERT INTO epub_books(target_id, position, title, chapter_start, "
                "export_path, export_fingerprint, exported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    target_id,
                    position,
                    title,
                    start,
                    prev.export_path if prev else None,
                    prev.export_fingerprint if prev else None,
                    prev.exported_at if prev else None,
                ),
            )
    return await list_books(db, target_id)


async def mark_exported(
    db: aiosqlite.Connection, target_id: int, book_id: int, export_path: str, fingerprint: str
) -> None:
    """Record a fresh export, and drop the export record of any other book of
    the series that pointed at the same file (after a re-numbering, the
    file now holds this book's content, so it no longer belongs to them)."""
    async with transaction(db):
        await db.execute(
            "UPDATE epub_books SET export_path = NULL, export_fingerprint = NULL, "
            "exported_at = NULL WHERE target_id = ? AND id != ? AND export_path = ?",
            (target_id, book_id, export_path),
        )
        await db.execute(
            "UPDATE epub_books SET export_path = ?, export_fingerprint = ?, exported_at = ? "
            "WHERE id = ?",
            (export_path, fingerprint, now_iso(), book_id),
        )
