from __future__ import annotations

import json

from fastapi import APIRouter, Request

from backend.dependencies import DbDep, EventBusDep
from backend.events import maintenance_event
from backend.exceptions import BadRequestError, ConflictError, NotFoundError
from backend.maintenance import service
from backend.maintenance.schemas import (
    MaintenanceJob,
    MaintenanceProgressOut,
    MaintenanceScheduleIn,
    UpdateCheckOut,
)
from backend.maintenance.update_check import check_for_updates

router = APIRouter(tags=["maintenance"])

SUPPORTED_KINDS = {
    "rename_chapters",
    "regenerate_series_metadata",
    "rebuild_library",
    "push_komga_series_status",
    "update_lxc",
    "unwatch_ended_series",
}

# Kinds whose schedule request must carry credentials in `params`. We stash
# those params in worker memory before creating the DB row so the SQLite
# table never sees them.
KINDS_REQUIRING_PARAMS = {"push_komga_series_status"}


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
    if body.kind in KINDS_REQUIRING_PARAMS:
        # Fail fast before persisting a pending row that the worker would
        # immediately mark failed for the same reason.
        from backend.maintenance.komga import validate_credentials

        try:
            validate_credentials(body.params)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
    created = await service.create_pending(db, body.kind)
    if body.kind in KINDS_REQUIRING_PARAMS:
        # Stash *after* the row exists so the worker can never claim a job
        # whose params we forgot to register. The params dict lives only in
        # the worker's process memory and is dropped on terminal transition.
        request.app.state.maintenance_worker.stash_params(created.id, body.params or {})
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
        # Drop any stashed credentials for a job that will never run.
        request.app.state.maintenance_worker.drop_params(job_id)
    else:
        request.app.state.maintenance_worker.request_cancel(job_id)
    refreshed = await service.get_job(db, job_id)
    if refreshed is None:
        raise NotFoundError("maintenance job not found")
    bus.publish(maintenance_event("updated", id=job_id))
    return refreshed


@router.get("/maintenance/update-check", operation_id="checkForUpdates")
async def check_for_updates_endpoint(force: bool = False) -> UpdateCheckOut:
    """Compare the installed checkout to upstream main on GitHub.

    `force=true` bypasses the 60 s in-process cache for an explicit refresh
    button; default polling reuses the cached result so the UI can refetch
    aggressively without burning GitHub's anon rate limit.
    """
    result = await check_for_updates(force=force)
    return UpdateCheckOut(
        branch=result.branch,
        current_sha=result.current_sha,
        latest_sha=result.latest_sha,
        latest_message=result.latest_message,
        latest_committed_at=result.latest_committed_at,
        behind=result.behind,
        reason=result.reason,
    )


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
