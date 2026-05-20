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


class MaintenanceProgressOut(BaseModel):
    status: str
    total: int
    done: int
    lines: list[str]
