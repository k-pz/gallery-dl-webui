from __future__ import annotations

from pydantic import BaseModel

from backend.storage import Download, TargetSummary


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


class ProgressOut(BaseModel):
    status: str
    files_expected: int | None
    files_present: int
    chapters: list[ChapterProgress]


class AppConfigOut(BaseModel):
    postprocess_root: str | None
    postprocess_default_output_dir: str | None
    postprocess_known_output_dirs: list[str]
    delete_raw_after_pack: bool
    default_watch_period: str


class AppConfigIn(BaseModel):
    postprocess_root: str | None
    postprocess_default_output_dir: str | None
    delete_raw_after_pack: bool
    default_watch_period: str | None = None


class TargetOut(BaseModel):
    id: int
    url: str
    name: str | None
    extractor: str | None
    output_dir: str | None
    watched: bool
    watch_period: str | None
    last_polled_at: str | None
    created_at: str
    last_download_id: int | None
    last_status: str | None
    last_finished_at: str | None
    last_created_at: str | None
    download_count: int

    @classmethod
    def from_summary(cls, s: TargetSummary) -> TargetOut:
        return cls(
            id=s.target.id,
            url=s.target.url,
            name=s.target.name,
            extractor=s.target.extractor,
            output_dir=s.target.output_dir,
            watched=s.target.watched,
            watch_period=s.target.watch_period,
            last_polled_at=s.target.last_polled_at,
            created_at=s.target.created_at,
            last_download_id=s.last_download_id,
            last_status=s.last_status,
            last_finished_at=s.last_finished_at,
            last_created_at=s.last_created_at,
            download_count=s.download_count,
        )


class TargetUpdate(BaseModel):
    watched: bool | None = None
    # Empty string clears the per-target override (falls back to default).
    watch_period: str | None = None
    output_dir: str | None = None


class DirEntry(BaseModel):
    path: str
    name: str
    depth: int


class DirCreate(BaseModel):
    path: str


class LibraryImportResult(BaseModel):
    imported: int
    updated: int
    errors: list[str]
