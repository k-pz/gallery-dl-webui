from __future__ import annotations

import json
from typing import Any

import aiosqlite
from pydantic import BaseModel, field_validator


class Target(BaseModel):
    """A row from the `targets` table, optionally joined with summary stats.

    The summary fields (`last_*`, `download_count`) are hydrated only when
    the row came from `service.list_all` / `service.get_summary` (those
    queries do the JOIN); otherwise they're None/0.

    `tags` round-trips through a JSON-encoded TEXT column; the field
    validator parses the raw string back into a list of strings.
    """

    id: int
    url: str
    name: str | None
    extractor: str | None
    output_dir: str | None
    watched: bool
    watch_period: str | None
    last_polled_at: str | None
    created_at: str
    tags: list[str] = []
    reading_direction: str | None = None
    series_status: str | None = None
    # Joined summary fields (None/0 when not from the summary SELECT):
    last_download_id: int | None = None
    last_status: str | None = None
    last_finished_at: str | None = None
    last_created_at: str | None = None
    download_count: int = 0

    @field_validator("tags", mode="before")
    @classmethod
    def _decode_tags(cls, v: Any) -> Any:
        # The DB column is a JSON-encoded list-of-strings (or NULL); the
        # router/service path may also pass an already-decoded list.
        if v is None or v == "":
            return []
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return v

    @field_validator("watched", mode="before")
    @classmethod
    def _coerce_watched(cls, v: Any) -> bool:
        return bool(v)

    @field_validator("download_count", mode="before")
    @classmethod
    def _coerce_download_count(cls, v: Any) -> int:
        return int(v) if v is not None else 0

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> Target:
        return cls.model_validate(dict(row))


class TargetUpdate(BaseModel):
    watched: bool | None = None
    # Empty string clears the per-target override (falls back to default).
    watch_period: str | None = None
    output_dir: str | None = None
    tags: list[str] | None = None
    reading_direction: str | None = None
    # Empty string clears; otherwise one of postprocess.SERIES_STATUSES.
    series_status: str | None = None
