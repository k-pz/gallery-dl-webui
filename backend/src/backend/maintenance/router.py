from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from backend.dependencies import DbDep, EventBusDep
from backend.events import maintenance_event
from backend.maintenance import service
from backend.maintenance.schemas import (
    MaintenanceJobOut,
    MaintenanceProgressOut,
    MaintenanceScheduleIn,
)

router = APIRouter(tags=["maintenance"])

SUPPORTED_KINDS = {
    "rename_chapters",
    "regenerate_series_metadata",
    "rebuild_library",
    "push_komga_series_status",
    "update_lxc",
}

# Kinds whose schedule request must carry credentials in `params`. We stash
# those params in worker memory before creating the DB row so the SQLite
# table never sees them.
KINDS_REQUIRING_PARAMS = {"push_komga_series_status"}


def _to_out(job) -> MaintenanceJobOut:
    parsed = None
    if job.result_json:
        try:
            loaded = json.loads(job.result_json)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            parsed = loaded
    return MaintenanceJobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=parsed,
        error=job.error,
    )


@router.get("/maintenance/jobs", operation_id="listMaintenanceJobs")
async def list_maintenance_jobs(db: DbDep) -> list[MaintenanceJobOut]:
    jobs = await service.list_jobs(db)
    return [_to_out(j) for j in jobs]


@router.post("/maintenance/jobs", operation_id="scheduleMaintenanceJob")
async def schedule_maintenance_job(
    body: MaintenanceScheduleIn,
    db: DbDep,
    request: Request,
    bus: EventBusDep,
) -> MaintenanceJobOut:
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(status_code=400, detail=f"unsupported maintenance kind: {body.kind}")
    if body.kind in KINDS_REQUIRING_PARAMS:
        # Fail fast before persisting a pending row that the worker would
        # immediately mark failed for the same reason.
        from backend.maintenance.komga import validate_credentials

        try:
            validate_credentials(body.params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    created = await service.create_pending(db, body.kind)
    if body.kind in KINDS_REQUIRING_PARAMS:
        # Stash *after* the row exists so the worker can never claim a job
        # whose params we forgot to register. The params dict lives only in
        # the worker's process memory and is dropped on terminal transition.
        request.app.state.maintenance_worker.stash_params(created.id, body.params or {})
    request.app.state.maintenance_worker.notify()
    bus.publish(maintenance_event("created", id=created.id))
    return _to_out(created)


@router.post("/maintenance/jobs/{job_id}/cancel", operation_id="cancelMaintenanceJob")
async def cancel_maintenance_job(
    job_id: int,
    db: DbDep,
    request: Request,
    bus: EventBusDep,
) -> MaintenanceJobOut:
    job = await service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="maintenance job not found")
    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"maintenance job already {job.status}")
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
        raise HTTPException(status_code=404, detail="maintenance job not found")
    bus.publish(maintenance_event("updated", id=job_id))
    return _to_out(refreshed)


@router.get("/maintenance/jobs/{job_id}/progress", operation_id="getMaintenanceJobProgress")
async def get_maintenance_job_progress(
    job_id: int,
    db: DbDep,
    request: Request,
) -> MaintenanceProgressOut:
    job = await service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="maintenance job not found")
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
    if job.status == "completed" and job.result_json:
        summary.append(f"done: {job.result_json}")
    elif job.status == "cancelled":
        if job.result_json:
            summary.append(f"cancelled: {job.result_json}")
        else:
            summary.append("cancelled")
    elif job.status == "failed" and job.error:
        summary.append(f"failed: {job.error}")
    return MaintenanceProgressOut(status=job.status, total=0, done=0, lines=summary)
