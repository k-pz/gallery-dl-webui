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


class ChangelogEntryOut(BaseModel):
    """One entry in the changelog list returned by `/api/maintenance/update-check`.

    Default-branch tracking populates `body` with the GitHub Release notes;
    preview-ref tracking leaves it None and `title` carries the commit
    subject. `ref` is the tag (e.g. `v1.1.0`) or the full commit SHA.
    """

    title: str
    body: str | None
    ref: str
    published_at: str | None
    html_url: str | None


class UpdateCheckOut(BaseModel):
    """Snapshot returned by `/api/maintenance/update-check`.

    Almost every field is nullable because the underlying check has
    several inert outcomes (no git metadata, network unreachable,
    non-GitHub origin); `reason` carries the machine-readable label.
    `changelog` is empty in those cases and on preview refs where the
    compare API failed.
    """

    branch: str | None
    current_sha: str | None
    current_version: str | None
    tracked_ref: str | None
    tracked_ref_is_default: bool
    latest_sha: str | None
    latest_message: str | None
    latest_committed_at: str | None
    latest_version: str | None
    behind: bool | None
    changelog: list[ChangelogEntryOut]
    available_tags: list[str]
    reason: str | None


class UpdateRefOut(BaseModel):
    """Preview ref persisted in app_config under `update_preview_ref`.

    `ref` is null when no preview is set — the checker falls back to the
    branch read from `.git/HEAD` (`main` in production).
    """

    ref: str | None


class UpdateRefIn(BaseModel):
    """Mirror of UpdateRefOut for the PUT endpoint.

    An empty / whitespace-only string is normalised to None on the
    server so the user can clear the preview ref by emptying the input.
    """

    ref: str | None
