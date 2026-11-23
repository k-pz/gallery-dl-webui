from __future__ import annotations

from typing import Literal

import aiosqlite
from pydantic import BaseModel, Field

from backend.epub.library import StoredBook


class EpubBook(BaseModel):
    """A row from the `epub_books` table."""

    id: int
    target_id: int
    position: int
    title: str | None
    chapter_start: float
    chapter_end: float | None
    export_path: str | None
    export_fingerprint: str | None
    exported_at: str | None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> EpubBook:
        return cls.model_validate(dict(row))

    def to_stored(self) -> StoredBook:
        return StoredBook(
            id=self.id,
            position=self.position,
            title=self.title,
            chapter_start=self.chapter_start,
            chapter_end=self.chapter_end,
            export_path=self.export_path,
            export_fingerprint=self.export_fingerprint,
            exported_at=self.exported_at,
        )


class EpubBookIn(BaseModel):
    """One book of a series: an inclusive chapter-number range.

    `chapter_end` null leaves the book open-ended (only allowed for the last
    book) so chapters downloaded later land in it. A blank `title` falls back
    to "<Series>, Vol. <n>".
    """

    title: str | None = None
    chapter_start: float = Field(allow_inf_nan=False)
    chapter_end: float | None = Field(default=None, allow_inf_nan=False)


class EpubBooksIn(BaseModel):
    books: list[EpubBookIn]


class EpubChapterOut(BaseModel):
    number: str
    title: str
    volume: str
    pages: int
    file_name: str
    # Position of the book this chapter falls in; null when unassigned.
    book_position: int | None


class EpubBookOut(BaseModel):
    id: int
    position: int
    # Effective title (custom title or the "<Series>, Vol. <n>" default).
    title: str
    custom_title: str | None
    chapter_start: float
    chapter_end: float | None
    chapter_count: int
    page_count: int
    first_chapter: str | None
    last_chapter: str | None
    # empty: no chapters on disk in range; not_exported: never exported (or
    # the file is gone); outdated: chapters or metadata changed since the
    # last export; exported: the file on disk is current.
    status: Literal["empty", "not_exported", "outdated", "exported"]
    exported_at: str | None
    # Name of the exported file, when one exists on disk.
    file_name: str | None


class EpubOverview(BaseModel):
    target_id: int
    series: str | None
    series_dir: str | None
    export_dir: str
    chapters: list[EpubChapterOut]
    books: list[EpubBookOut]
    # Chapter numbers that fall in no book.
    unassigned: list[str]
    # Ranges derived from the chapters' Volume metadata; empty when the
    # source exposes no (consistent) volumes.
    suggested_books: list[EpubBookIn]


class EpubExportAllResult(BaseModel):
    exported: int
    failed: int
    errors: list[str]
