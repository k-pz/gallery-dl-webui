from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from backend.dependencies import DbDep
from backend.maintenance import service
from backend.maintenance.schemas import MaintenanceJobOut, MaintenanceScheduleIn

router = APIRouter(tags=["maintenance"])

SUPPORTED_KINDS = {"rename_chapters"}


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
) -> MaintenanceJobOut:
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(status_code=400, detail=f"unsupported maintenance kind: {body.kind}")
    created = await service.create_pending(db, body.kind)
    request.app.state.maintenance_worker.notify()
    return _to_out(created)
