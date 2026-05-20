from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MaintenanceJob:
    id: int
    kind: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    result_json: str | None
    error: str | None
