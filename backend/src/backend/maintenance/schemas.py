from __future__ import annotations

import json
from typing import Any

import aiosqlite
from pydantic import BaseModel, field_validator


class MaintenanceJob(BaseModel):
    """A row from `maintenance_jobs`. The DB column `result_json` is parsed
    into the `result` dict on validation (NULL / non-dict / invalid JSON all
    collapse to None — same semantics as the previous `_to_out` translator
    in the router)."""

    id: int
    kind: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    result: dict[str, Any] | None
    error: str | None

    @field_validator("result", mode="before")
    @classmethod
    def _decode_result_json(cls, v: Any) -> Any:
        # Accept the raw `result_json` text column or an already-decoded dict.
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return v

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> MaintenanceJob:
        # The column is `result_json`; the field is `result`. Alias on the
        # way in so the validator sees the JSON text.
        payload = dict(row)
        payload["result"] = payload.pop("result_json", None)
        return cls.model_validate(payload)


class MaintenanceScheduleIn(BaseModel):
    kind: str


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
