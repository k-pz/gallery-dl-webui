from __future__ import annotations

from pydantic import BaseModel

from backend.targets.models import TargetSummary


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
    tags: list[str]
    reading_direction: str | None

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
            tags=list(s.target.tags),
            reading_direction=s.target.reading_direction,
        )


class TargetUpdate(BaseModel):
    watched: bool | None = None
    # Empty string clears the per-target override (falls back to default).
    watch_period: str | None = None
    output_dir: str | None = None
    tags: list[str] | None = None
    reading_direction: str | None = None
