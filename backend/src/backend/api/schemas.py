from __future__ import annotations

from pydantic import BaseModel

from backend.storage import Download


class DownloadCreate(BaseModel):
    url: str


class DownloadOut(BaseModel):
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
    error: str | None
    postprocess_status: str | None
    postprocess_chapters_packed: int | None
    postprocess_error: str | None

    @classmethod
    def from_download(cls, d: Download) -> DownloadOut:
        return cls(
            id=d.id,
            url=d.url,
            extractor=d.extractor,
            status=d.status,
            created_at=d.created_at,
            started_at=d.started_at,
            finished_at=d.finished_at,
            exit_code=d.exit_code,
            files_downloaded=d.files_downloaded,
            files_expected=d.files_expected,
            error=d.error,
            postprocess_status=d.postprocess_status,
            postprocess_chapters_packed=d.postprocess_chapters_packed,
            postprocess_error=d.postprocess_error,
        )


class ChapterProgress(BaseModel):
    name: str
    files_total: int
    files_present: int


class ProgressOut(BaseModel):
    status: str
    files_expected: int | None
    files_present: int
    chapters: list[ChapterProgress]


class AppConfigOut(BaseModel):
    postprocess_output_dir: str | None
    delete_raw_after_pack: bool


class AppConfigIn(BaseModel):
    postprocess_output_dir: str | None
    delete_raw_after_pack: bool
