from __future__ import annotations

from dataclasses import dataclass

import aiosqlite


@dataclass
class Download:
    id: int
    url: str
    extractor: str | None
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    files_downloaded: int
    files_expected: int | None
    chapters_total: int | None
    error: str | None
    postprocess_status: str | None
    postprocess_chapters_packed: int | None
    postprocess_error: str | None
    output_dir: str | None
    target_id: int | None = None


def row_to_download(row: aiosqlite.Row) -> Download:
    return Download(
        id=row["id"],
        url=row["url"],
        extractor=row["extractor"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        exit_code=row["exit_code"],
        files_downloaded=row["files_downloaded"],
        files_expected=row["files_expected"],
        chapters_total=row["chapters_total"],
        error=row["error"],
        postprocess_status=row["postprocess_status"],
        postprocess_chapters_packed=row["postprocess_chapters_packed"],
        postprocess_error=row["postprocess_error"],
        output_dir=row["output_dir"],
        target_id=row["target_id"],
    )
