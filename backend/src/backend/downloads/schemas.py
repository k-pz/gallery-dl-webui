from __future__ import annotations

from pydantic import BaseModel

from backend.downloads.models import Download


class DownloadCreate(BaseModel):
    url: str
    output_dir: str | None = None


class DownloadOut(BaseModel):
    id: int
    url: str
    name: str | None
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
    target_id: int | None

    @classmethod
    def from_download(cls, d: Download, name: str | None = None) -> DownloadOut:
        return cls(
            id=d.id,
            url=d.url,
            name=name,
            extractor=d.extractor,
            status=d.status,
            created_at=d.created_at,
            started_at=d.started_at,
            finished_at=d.finished_at,
            exit_code=d.exit_code,
            files_downloaded=d.files_downloaded,
            files_expected=d.files_expected,
            chapters_total=d.chapters_total,
            error=d.error,
            postprocess_status=d.postprocess_status,
            postprocess_chapters_packed=d.postprocess_chapters_packed,
            postprocess_error=d.postprocess_error,
            output_dir=d.output_dir,
            target_id=d.target_id,
        )


class ChapterProgress(BaseModel):
    name: str
    files_total: int
    files_present: int
    stage: str


class ProgressOut(BaseModel):
    status: str
    files_expected: int | None
    files_present: int
    chapters: list[ChapterProgress]
