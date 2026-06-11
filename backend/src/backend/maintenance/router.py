from __future__ import annotations

import json

from fastapi import APIRouter, Request

from backend.app_config import service as app_config_service
from backend.dependencies import DbDep, EventBusDep
from backend.events import maintenance_event
from backend.exceptions import BadRequestError, ConflictError, NotFoundError
from backend.maintenance import service
from backend.maintenance.schemas import (
    ChangelogEntryOut,
    MaintenanceJob,
    MaintenanceProgressOut,
    MaintenanceScheduleIn,
    UpdateCheckOut,
    UpdateRefIn,
    UpdateRefOut,
)
from backend.maintenance.update_check import check_for_updates
from backend.maintenance.worker import UPDATE_PREVIEW_REF_KEY

router = APIRouter(tags=["maintenance"])

SUPPORTED_KINDS = {
    "rename_chapters",
    "regenerate_series_metadata",
    "refresh_series_metadata",
    "rebuild_library",
    "push_komga_series_status",
    "sync_komga_metadata",
    "update_lxc",
    "unwatch_ended_series",
}

# Kinds that talk to Komga and therefore need credentials in app_config.
KOMGA_KINDS = {"push_komga_series_status", "sync_komga_metadata"}


@router.get("/maintenance/jobs", operation_id="listMaintenanceJobs")
async def list_maintenance_jobs(db: DbDep) -> list[MaintenanceJob]:
    return await service.list_jobs(db)


@router.post("/maintenance/jobs", operation_id="scheduleMaintenanceJob")
async def schedule_maintenance_job(
    body: MaintenanceScheduleIn,
    db: DbDep,
    request: Request,
    bus: EventBusDep,
) -> MaintenanceJob:
    if body.kind not in SUPPORTED_KINDS:
        raise BadRequestError(f"unsupported maintenance kind: {body.kind}")
    if body.kind in KOMGA_KINDS:
        # Fail fast before persisting a pending row that the worker would
        # immediately mark failed for the same reason. Credentials live in
        # app_config (Config tab → Komga sync); the worker re-reads them when
        # the job is claimed.
        from backend.maintenance.komga import load_credentials

        cfg = await app_config_service.get_all(db)
        try:
            load_credentials(cfg)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
    created = await service.create_pending(db, body.kind)
    request.app.state.maintenance_worker.notify()
    bus.publish(maintenance_event("created", id=created.id))
    return created


@router.post("/maintenance/jobs/{job_id}/cancel", operation_id="cancelMaintenanceJob")
async def cancel_maintenance_job(
    job_id: int,
    db: DbDep,
    request: Request,
    bus: EventBusDep,
) -> MaintenanceJob:
    job = await service.get_job(db, job_id)
    if job is None:
        raise NotFoundError("maintenance job not found")
    if job.status in ("completed", "failed", "cancelled"):
        raise ConflictError(f"maintenance job already {job.status}")
    # Two paths: a still-pending row can be flipped directly; an in-flight job
    # gets a soft signal that the worker checks at the top of each iteration.
    if job.status == "pending":
        await service.cancel_pending(db, job_id)
    else:
        request.app.state.maintenance_worker.request_cancel(job_id)
    refreshed = await service.get_job(db, job_id)
    if refreshed is None:
        raise NotFoundError("maintenance job not found")
    bus.publish(maintenance_event("updated", id=job_id))
    return refreshed


@router.get("/maintenance/update-check", operation_id="checkForUpdates")
async def check_for_updates_endpoint(db: DbDep, force: bool = False) -> UpdateCheckOut:
    """Compare the installed checkout to the tracked ref on GitHub.

    The tracked ref defaults to whatever's in `.git/HEAD` (`main` in
    production) but can be overridden via `PUT /maintenance/update-ref`
    to preview an unreleased branch / tag / SHA. `force=true` bypasses
    the 60 s in-process cache for an explicit refresh button; default
    polling reuses the cached result so the UI can refetch aggressively
    without burning GitHub's anon rate limit.
    """
    cfg = await app_config_service.get_all(db)
    ref_override = _read_preview_ref(cfg)
    result = await check_for_updates(force=force, ref_override=ref_override)
    return UpdateCheckOut(
        branch=result.branch,
        current_sha=result.current_sha,
        current_version=result.current_version,
        tracked_ref=result.tracked_ref,
        tracked_ref_is_default=result.tracked_ref_is_default,
        latest_sha=result.latest_sha,
        latest_message=result.latest_message,
        latest_committed_at=result.latest_committed_at,
        latest_version=result.latest_version,
        behind=result.behind,
        changelog=[
            ChangelogEntryOut(
                title=entry.title,
                body=entry.body,
                ref=entry.ref,
                published_at=entry.published_at,
                html_url=entry.html_url,
            )
            for entry in result.changelog
        ],
        available_tags=result.available_tags,
        reason=result.reason,
    )


@router.get("/maintenance/update-ref", operation_id="getUpdatePreviewRef")
async def get_update_preview_ref(db: DbDep) -> UpdateRefOut:
    """Return the currently-configured preview ref, or null for the default.

    Stored in app_config under `update_preview_ref` so it persists across
    restarts. When null, the update checker uses the branch from
    `.git/HEAD` (production: `main`).
    """
    cfg = await app_config_service.get_all(db)
    return UpdateRefOut(ref=_read_preview_ref(cfg))


@router.put("/maintenance/update-ref", operation_id="setUpdatePreviewRef")
async def set_update_preview_ref(body: UpdateRefIn, db: DbDep) -> UpdateRefOut:
    """Persist a preview ref, or clear it when null/empty.

    No upstream validation here: a wrong ref will surface as
    `branch_not_on_remote` from the next `/update-check`, and the user
    can fix it without the round-trip + rate-limit cost of an extra
    GitHub call per save.
    """
    raw = body.ref
    normalised: str | None
    if raw is None:
        normalised = None
    else:
        stripped = raw.strip()
        normalised = stripped if stripped else None
    await app_config_service.set_many(db, {UPDATE_PREVIEW_REF_KEY: normalised})
    return UpdateRefOut(ref=normalised)


def _read_preview_ref(cfg: dict[str, object]) -> str | None:
    """Pull `update_preview_ref` out of the app_config snapshot, defaulting to None."""
    value = cfg.get(UPDATE_PREVIEW_REF_KEY)
    if isinstance(value, str) and value:
        return value
    return None


@router.get("/maintenance/jobs/{job_id}/progress", operation_id="getMaintenanceJobProgress")
async def get_maintenance_job_progress(
    job_id: int,
    db: DbDep,
    request: Request,
) -> MaintenanceProgressOut:
    job = await service.get_job(db, job_id)
    if job is None:
        raise NotFoundError("maintenance job not found")
    snapshot = request.app.state.maintenance_live.snapshot(job_id)
    if snapshot is not None:
        return MaintenanceProgressOut(
            status=job.status,
            total=snapshot.total,
            done=snapshot.done,
            lines=snapshot.lines,
        )
    # Terminal (or pending) — no live state. Synthesize a one-line summary so
    # callers can still render something useful after the worker has cleared
    # its in-memory buffer.
    summary: list[str] = []
    if job.status == "completed" and job.result is not None:
        summary.append(f"done: {json.dumps(job.result)}")
    elif job.status == "cancelled":
        if job.result is not None:
            summary.append(f"cancelled: {json.dumps(job.result)}")
        else:
            summary.append("cancelled")
    elif job.status == "failed" and job.error:
        summary.append(f"failed: {job.error}")
    return MaintenanceProgressOut(status=job.status, total=0, done=0, lines=summary)
