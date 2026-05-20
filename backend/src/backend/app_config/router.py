from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app_config import service
from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
    DEFAULT_DELETE_RAW,
    DEFAULT_READING_DIRECTION,
    DEFAULT_WATCH_PERIOD,
    READING_DIRECTIONS,
)
from backend.app_config.exceptions import DefaultOutputDirWithoutRoot
from backend.app_config.schemas import AppConfigIn, AppConfigOut
from backend.dependencies import DbDep
from backend.downloads.postprocess import validate_chapter_naming_template
from backend.output_dirs.utils import coerce_optional, validate_root, validate_under_root
from backend.targets.utils import parse_duration

router = APIRouter(tags=["config"])


def _load_config(cfg: dict[str, object]) -> AppConfigOut:
    root = cfg.get("postprocess_root")
    if not isinstance(root, str):
        root = None
    default = cfg.get("postprocess_default_output_dir")
    if not isinstance(default, str):
        default = None
    known = cfg.get("postprocess_known_output_dirs")
    if not isinstance(known, list):
        known = []
    known_str = [k for k in known if isinstance(k, str)]
    period = cfg.get("default_watch_period")
    if not isinstance(period, str) or not period:
        period = DEFAULT_WATCH_PERIOD
    chapter_template = cfg.get("chapter_naming_template")
    if not isinstance(chapter_template, str) or not chapter_template:
        chapter_template = DEFAULT_CHAPTER_NAMING_TEMPLATE
    reading_direction = cfg.get("default_reading_direction")
    if not isinstance(reading_direction, str) or reading_direction not in READING_DIRECTIONS:
        reading_direction = DEFAULT_READING_DIRECTION
    return AppConfigOut(
        postprocess_root=root,
        postprocess_default_output_dir=default,
        postprocess_known_output_dirs=known_str,
        delete_raw_after_pack=bool(cfg.get("delete_raw_after_pack", DEFAULT_DELETE_RAW)),
        default_watch_period=period,
        chapter_naming_template=chapter_template,
        default_reading_direction=reading_direction,
    )


@router.get("/config", operation_id="getConfig")
async def get_config(db: DbDep) -> AppConfigOut:
    return _load_config(await service.get_all(db))


@router.put("/config", operation_id="putConfig")
async def put_config(body: AppConfigIn, db: DbDep) -> AppConfigOut:
    root_raw = coerce_optional(body.postprocess_root)
    default_raw = coerce_optional(body.postprocess_default_output_dir)

    root_path = validate_root(root_raw) if root_raw else None
    default_path = None
    if default_raw is not None:
        if root_path is None:
            raise DefaultOutputDirWithoutRoot()
        default_path = validate_under_root(
            default_raw, root_path, field="postprocess_default_output_dir"
        )

    period_raw = coerce_optional(body.default_watch_period) or DEFAULT_WATCH_PERIOD
    try:
        parse_duration(period_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    template_raw = coerce_optional(body.chapter_naming_template) or DEFAULT_CHAPTER_NAMING_TEMPLATE
    try:
        validate_chapter_naming_template(template_raw)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid chapter_naming_template: {exc}",
        ) from exc
    direction_raw = (
        coerce_optional(body.default_reading_direction) or DEFAULT_READING_DIRECTION
    ).lower()
    if direction_raw not in READING_DIRECTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid default_reading_direction: {direction_raw!r}; "
                f"expected one of {sorted(READING_DIRECTIONS)}"
            ),
        )

    # When the root changes, drop the remembered dirs — they may no longer be valid.
    existing = await service.get_all(db)
    prior_root = existing.get("postprocess_root")
    known = existing.get("postprocess_known_output_dirs") or []
    if not isinstance(known, list):
        known = []
    root_str = str(root_path) if root_path else None
    if root_str != prior_root:
        known = []

    updates: dict[str, object] = {
        "postprocess_root": root_str,
        "postprocess_default_output_dir": str(default_path) if default_path else None,
        "postprocess_known_output_dirs": known,
        "delete_raw_after_pack": bool(body.delete_raw_after_pack),
        "default_watch_period": period_raw,
        "chapter_naming_template": template_raw,
        "default_reading_direction": direction_raw,
    }
    await service.set_many(db, updates)
    return _load_config(updates)
