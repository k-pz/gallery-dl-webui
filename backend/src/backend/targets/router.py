from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app_config import service as app_config_service
from backend.app_config.exceptions import PostprocessRootNotConfigured
from backend.dependencies import DbDep
from backend.downloads import service as downloads_service
from backend.downloads.dependencies import WorkerDep
from backend.output_dirs.utils import coerce_optional, validate_under_root
from backend.targets import service
from backend.targets.dependencies import PollerDep, TargetDep
from backend.targets.exceptions import (
    TargetHasActiveDownload,
    TargetHasActiveDownloadOnDelete,
    TargetNotFound,
)
from backend.targets.models import UNSET, Unset
from backend.targets.schemas import TargetOut, TargetUpdate
from backend.targets.utils import parse_duration

router = APIRouter(tags=["targets"])


@router.get("/targets", operation_id="listTargets")
async def list_targets(db: DbDep) -> list[TargetOut]:
    rows = await service.list_all(db)
    return [TargetOut.from_summary(s) for s in rows]


@router.get("/targets/{target_id}", operation_id="getTarget")
async def get_target(target: TargetDep, db: DbDep) -> TargetOut:
    summary = await service.get_summary(db, target.id)
    if summary is None:
        raise TargetNotFound()
    return TargetOut.from_summary(summary)


@router.patch("/targets/{target_id}", operation_id="updateTarget")
async def update_target(
    body: TargetUpdate,
    target: TargetDep,
    db: DbDep,
    poller: PollerDep,
) -> TargetOut:
    new_watched = target.watched if body.watched is None else body.watched
    new_period: str | None | Unset = UNSET
    new_output_dir: str | None | Unset = UNSET

    if body.watch_period is not None:
        cleaned = body.watch_period.strip()
        if cleaned == "":
            new_period = None
        else:
            try:
                parse_duration(cleaned)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            new_period = cleaned

    if body.output_dir is not None:
        out_raw = coerce_optional(body.output_dir)
        if out_raw is None:
            new_output_dir = None
        else:
            cfg = await app_config_service.get_all(db)
            root_raw = cfg.get("postprocess_root")
            if not isinstance(root_raw, str) or not root_raw:
                raise PostprocessRootNotConfigured("output_dir")
            resolved = validate_under_root(out_raw, Path(root_raw), field="output_dir")
            new_output_dir = str(resolved)
            await app_config_service.remember_output_dir(db, new_output_dir)

    await service.update(
        db,
        target.id,
        watched=new_watched,
        watch_period=new_period,
        output_dir=new_output_dir,
    )

    if body.watched is True and not target.watched:
        poller.notify()
    summary = await service.get_summary(db, target.id)
    if summary is None:
        raise TargetNotFound()
    return TargetOut.from_summary(summary)


@router.post("/targets/{target_id}/poll", operation_id="pollTarget")
async def poll_target(target: TargetDep, db: DbDep, worker: WorkerDep) -> TargetOut:
    if await downloads_service.has_active_for_target(db, target.id):
        raise TargetHasActiveDownload()
    await downloads_service.insert_pending(
        db, target.url, target.extractor, output_dir=target.output_dir, target_id=target.id
    )
    await service.mark_polled(db, target.id)
    worker.notify()
    summary = await service.get_summary(db, target.id)
    if summary is None:
        raise TargetNotFound()
    return TargetOut.from_summary(summary)


@router.delete("/targets/{target_id}", operation_id="deleteTarget")
async def delete_target(target: TargetDep, db: DbDep) -> dict[str, bool]:
    if await downloads_service.has_active_for_target(db, target.id):
        raise TargetHasActiveDownloadOnDelete()
    await service.delete(db, target.id)
    return {"deleted": True}
