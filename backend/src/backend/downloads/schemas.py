from __future__ import annotations

from typing import Any

import aiosqlite
from pydantic import BaseModel


class DownloadCreate(BaseModel):
    url: str
    output_dir: str | None = None
    watched: bool = False
    tags: list[str] | None = None
    reading_direction: str | None = None


class Download(BaseModel):
    """A row from the `downloads` table, plus the joined target `name`.

    The same type is used internally (worker, services) and on the wire —
    `name` is None when the row was constructed without a JOIN against
    `targets`, and populated by `from_row_with_name` or set by the caller
    after a separate lookup.
    """

    id: int
    url: str
    name: str | None = None
    extractor: str | None
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    files_downloaded: int
    files_expected: int | None
    chapters_total: int | None
    chapters_discovered: int | None = None
    chapters_failed: int | None = None
    error: str | None
    postprocess_status: str | None
    postprocess_chapters_packed: int | None
    postprocess_error: str | None
    output_dir: str | None
    target_id: int | None = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> Download:
        """Build from a SELECT row. `name` is hydrated only when the SELECT
        joined `targets.name AS name`; otherwise it stays None."""
        payload: dict[str, Any] = dict(row)
        payload.setdefault("name", None)
        return cls.model_validate(payload)


class ChapterProgress(BaseModel):
    name: str
    files_total: int
    files_present: int
    stage: str
    status: str | None = None
    pages: int | None = None
    title: str | None = None
    date: str | None = None
    error: str | None = None


class ProgressOut(BaseModel):
    status: str
    files_expected: int | None
    files_present: int
    chapters_discovered: int | None = None
    chapters_needed: int | None = None
    chapters_downloaded: int = 0
    chapters_failed: int = 0
    chapters_skipped: int = 0
    chapters: list[ChapterProgress]
