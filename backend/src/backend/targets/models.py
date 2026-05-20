from __future__ import annotations

import json
from dataclasses import dataclass, field

import aiosqlite


@dataclass
class Target:
    id: int
    url: str
    name: str | None
    extractor: str | None
    output_dir: str | None
    watched: bool
    watch_period: str | None
    last_polled_at: str | None
    created_at: str
    tags: list[str] = field(default_factory=list)
    reading_direction: str | None = None
    series_status: str | None = None


@dataclass
class TargetSummary:
    target: Target
    last_download_id: int | None
    last_status: str | None
    last_finished_at: str | None
    last_created_at: str | None
    download_count: int


class Unset:
    """Sentinel allowing update_target to distinguish "leave as-is" from "set to NULL"."""


UNSET = Unset()


def _tags_from_row(value: object) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [t for t in parsed if isinstance(t, str)]


def row_to_target(row: aiosqlite.Row) -> Target:
    return Target(
        id=row["id"],
        url=row["url"],
        name=row["name"],
        extractor=row["extractor"],
        output_dir=row["output_dir"],
        watched=bool(row["watched"]),
        watch_period=row["watch_period"],
        last_polled_at=row["last_polled_at"],
        created_at=row["created_at"],
        tags=_tags_from_row(row["tags"]),
        reading_direction=row["reading_direction"],
        series_status=row["series_status"] if row["series_status"] else None,
    )


def row_to_target_summary(row: aiosqlite.Row) -> TargetSummary:
    return TargetSummary(
        target=row_to_target(row),
        last_download_id=row["last_download_id"],
        last_status=row["last_status"],
        last_finished_at=row["last_finished_at"],
        last_created_at=row["last_created_at"],
        download_count=row["download_count"] or 0,
    )
