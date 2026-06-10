from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from backend.app_config import service as app_config_service
from backend.app_config.constants import READING_DIRECTIONS
from backend.app_config.exceptions import PostprocessRootNotConfigured
from backend.dependencies import DbDep, EventBusDep
from backend.downloads import service as downloads_service
from backend.downloads.dependencies import WorkerDep
from backend.downloads.postprocess import SERIES_STATUSES, normalize_tags
from backend.events import downloads_event, targets_event
from backend.exceptions import BadRequestError
from backend.output_dirs.utils import coerce_optional, validate_under_root
from backend.targets import service
from backend.targets.dependencies import PollerDep, TargetDep
from backend.targets.exceptions import (
    TargetHasActiveDownload,
    TargetHasActiveDownloadOnDelete,
    TargetNotFound,
)
from backend.targets.schemas import PollWatchedResult, Target, TargetUpdate
from backend.targets.service import UNSET, Unset
from backend.targets.utils import parse_duration

router = APIRouter(tags=["targets"])


@router.get("/targets", operation_id="listTargets")
async def list_targets(db: DbDep) -> list[Target]:
    return await service.list_all(db)


@router.get("/targets/{target_id}", operation_id="getTarget")
async def get_target(target: TargetDep, db: DbDep) -> Target:
    summary = await service.get_summary(db, target.id)
    if summary is None:
        raise TargetNotFound()
    return summary


@router.patch("/targets/{target_id}", operation_id="updateTarget")
async def update_target(
    body: TargetUpdate,
    target: TargetDep,
    db: DbDep,
    poller: PollerDep,
    bus: EventBusDep,
) -> Target:
    new_watched = target.watched if body.watched is None else body.watched
    new_period: str | None | Unset = UNSET
    new_output_dir: str | None | Unset = UNSET
    new_tags: list[str] | None | Unset = UNSET
    new_direction: str | None | Unset = UNSET
    new_series_status: str | None | Unset = UNSET

    if body.watch_period is not None:
        cleaned = body.watch_period.strip()
        if cleaned == "":
            new_period = None
        else:
            try:
                parse_duration(cleaned)
            except ValueError as exc:
                raise BadRequestError(str(exc)) from exc
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

    if body.tags is not None:
        new_tags = normalize_tags(body.tags)

    if body.reading_direction is not None:
        cleaned_dir = body.reading_direction.strip().lower()
        if cleaned_dir == "":
            new_direction = None
        elif cleaned_dir not in READING_DIRECTIONS:
            raise BadRequestError(
                f"invalid reading_direction: {body.reading_direction!r}; "
                f"expected one of {sorted(READING_DIRECTIONS)}"
            )
        else:
            new_direction = cleaned_dir

    if body.series_status is not None:
        cleaned_status = body.series_status.strip()
        if cleaned_status == "":
            new_series_status = None
        elif cleaned_status not in SERIES_STATUSES:
            raise BadRequestError(
                f"invalid series_status: {body.series_status!r}; "
                f"expected one of {sorted(SERIES_STATUSES)}"
            )
        else:
            new_series_status = cleaned_status

    await service.update(
        db,
        target.id,
        watched=new_watched,
        watch_period=new_period,
        output_dir=new_output_dir,
        tags=new_tags,
        reading_direction=new_direction,
        series_status=new_series_status,
    )

    if body.watched is True and not target.watched:
        poller.notify()
    summary = await service.get_summary(db, target.id)
    if summary is None:
        raise TargetNotFound()
    bus.publish(targets_event("updated", id=target.id))
    return summary


@router.post("/targets/poll-watched", operation_id="pollWatchedTargets")
async def poll_watched_targets(db: DbDep, worker: WorkerDep, bus: EventBusDep) -> PollWatchedResult:
    """Queue a download for every watched series that may still get chapters.

    Mirrors a per-target poll fanned out over the watched library, minus the
    409: targets with an in-flight download are skipped (and counted) so one
    busy series never fails the batch.
    """
    scheduled = 0
    skipped_active = 0
    for target in await service.list_watched_refreshable(db):
        if await downloads_service.has_active_for_target(db, target.id):
            skipped_active += 1
            continue
        download = await downloads_service.insert_pending(
            db, target.url, target.extractor, output_dir=target.output_dir, target_id=target.id
        )
        await service.mark_polled(db, target.id)
        bus.publish(downloads_event("created", id=download.id))
        bus.publish(targets_event("updated", id=target.id))
        scheduled += 1
    if scheduled:
        worker.notify()
    return PollWatchedResult(scheduled=scheduled, skipped_active=skipped_active)


@router.post("/targets/{target_id}/poll", operation_id="pollTarget")
async def poll_target(target: TargetDep, db: DbDep, worker: WorkerDep, bus: EventBusDep) -> Target:
    if await downloads_service.has_active_for_target(db, target.id):
        raise TargetHasActiveDownload()
    download = await downloads_service.insert_pending(
        db, target.url, target.extractor, output_dir=target.output_dir, target_id=target.id
    )
    await service.mark_polled(db, target.id)
    worker.notify()
    bus.publish(downloads_event("created", id=download.id))
    bus.publish(targets_event("updated", id=target.id))
    summary = await service.get_summary(db, target.id)
    if summary is None:
        raise TargetNotFound()
    return summary


@router.delete("/targets/{target_id}", operation_id="deleteTarget")
async def delete_target(target: TargetDep, db: DbDep, bus: EventBusDep) -> dict[str, bool]:
    if await downloads_service.has_active_for_target(db, target.id):
        raise TargetHasActiveDownloadOnDelete()
    await service.delete(db, target.id)
    bus.publish(targets_event("deleted", id=target.id))
    return {"deleted": True}
