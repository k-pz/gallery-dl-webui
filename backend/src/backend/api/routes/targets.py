from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.api.deps import PollerDep, StorageDep, WorkerDep
from backend.api.schemas import TargetOut, TargetUpdate
from backend.durations import parse_duration
from backend.output_dirs import coerce_optional, validate_under_root
from backend.storage import UNSET, Unset

router = APIRouter(tags=["targets"])


@router.get("/targets", operation_id="listTargets")
async def list_targets(storage: StorageDep) -> list[TargetOut]:
    rows = await storage.list_targets()
    return [TargetOut.from_summary(s) for s in rows]


@router.get("/targets/{target_id}", operation_id="getTarget")
async def get_target(target_id: int, storage: StorageDep) -> TargetOut:
    summary = await storage.get_target_summary(target_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="target not found")
    return TargetOut.from_summary(summary)


@router.patch("/targets/{target_id}", operation_id="updateTarget")
async def update_target(
    target_id: int, body: TargetUpdate, storage: StorageDep, poller: PollerDep
) -> TargetOut:
    existing = await storage.get_target(target_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="target not found")

    new_watched = existing.watched if body.watched is None else body.watched
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
            cfg = await storage.get_app_config()
            root_raw = cfg.get("postprocess_root")
            if not isinstance(root_raw, str) or not root_raw:
                raise HTTPException(
                    status_code=400,
                    detail="output_dir requires postprocess_root to be configured",
                )
            resolved = validate_under_root(out_raw, Path(root_raw), field="output_dir")
            new_output_dir = str(resolved)
            await storage.remember_output_dir(new_output_dir)

    await storage.update_target(
        target_id,
        watched=new_watched,
        watch_period=new_period,
        output_dir=new_output_dir,
    )

    if body.watched is True and not existing.watched:
        poller.notify()
    summary = await storage.get_target_summary(target_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="target not found")
    return TargetOut.from_summary(summary)


@router.post("/targets/{target_id}/poll", operation_id="pollTarget")
async def poll_target(target_id: int, storage: StorageDep, worker: WorkerDep) -> TargetOut:
    target = await storage.get_target(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    if await storage.has_active_download_for_target(target_id):
        raise HTTPException(
            status_code=409,
            detail="target already has an active download — wait for it to finish",
        )
    await storage.insert_pending(
        target.url, target.extractor, output_dir=target.output_dir, target_id=target.id
    )
    await storage.mark_target_polled(target_id)
    worker.notify()
    summary = await storage.get_target_summary(target_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="target not found")
    return TargetOut.from_summary(summary)


@router.delete("/targets/{target_id}", operation_id="deleteTarget")
async def delete_target(target_id: int, storage: StorageDep) -> dict[str, bool]:
    target = await storage.get_target(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    if await storage.has_active_download_for_target(target_id):
        raise HTTPException(
            status_code=409,
            detail="target has an active download — cancel it first",
        )
    await storage.delete_target(target_id)
    return {"deleted": True}
