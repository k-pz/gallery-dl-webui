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


class UpdateCheckOut(BaseModel):
    """Snapshot returned by `/api/maintenance/update-check`.

    All fields are nullable because the underlying check has several
    inert outcomes (no git metadata, network unreachable, non-GitHub
    origin); `reason` carries the machine-readable label for those.
    """

    branch: str | None
    current_sha: str | None
    latest_sha: str | None
    latest_message: str | None
    latest_committed_at: str | None
    behind: bool | None
    reason: str | None
