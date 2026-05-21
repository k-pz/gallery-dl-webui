from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MaintenanceJobOut(BaseModel):
    id: int
    kind: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    result: dict[str, Any] | None
    error: str | None


class MaintenanceScheduleIn(BaseModel):
    kind: str
    # Per-job, non-persisted parameters. Used by the `push_komga_series_status`
    # kind to carry Komga URL + credentials from the schedule request into the
    # worker without writing them to the DB. Validated server-side per kind.
    params: dict[str, Any] | None = None


class MaintenanceProgressOut(BaseModel):
    status: str
    total: int
    done: int
    lines: list[str]
