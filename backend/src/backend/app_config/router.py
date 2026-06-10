from __future__ import annotations

from fastapi import APIRouter

from backend.app_config import service
from backend.app_config.constants import (
    DEFAULT_CHAPTER_NAMING_TEMPLATE,
    DEFAULT_DELETE_RAW,
    DEFAULT_EXCLUDED_DIR_NAMES,
    DEFAULT_MAX_PARALLEL_POSTPROCESS,
    DEFAULT_READING_DIRECTION,
    DEFAULT_WATCH_PERIOD,
    READING_DIRECTIONS,
)
from backend.app_config.exceptions import DefaultOutputDirWithoutRoot
from backend.app_config.schemas import AppConfigIn, AppConfigOut
from backend.comic_metadata import validate_chapter_naming_template
from backend.dependencies import DbDep, EventBusDep
from backend.events import config_event
from backend.exceptions import BadRequestError
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
    excluded_raw = cfg.get("postprocess_excluded_dir_names")
    if isinstance(excluded_raw, list):
        excluded = [e for e in excluded_raw if isinstance(e, str) and e]
    else:
        # First load (or a wipe) — surface the package defaults so the user
        # can opt out by editing the list, not by guessing what NAS-mount
        # trash dirs we filter behind the scenes.
        excluded = list(DEFAULT_EXCLUDED_DIR_NAMES)
    period = cfg.get("default_watch_period")
    if not isinstance(period, str) or not period:
        period = DEFAULT_WATCH_PERIOD
    chapter_template = cfg.get("chapter_naming_template")
    if not isinstance(chapter_template, str) or not chapter_template:
        chapter_template = DEFAULT_CHAPTER_NAMING_TEMPLATE
    reading_direction = cfg.get("default_reading_direction")
    if not isinstance(reading_direction, str) or reading_direction not in READING_DIRECTIONS:
        reading_direction = DEFAULT_READING_DIRECTION
    max_postprocess = _coerce_clamped_int(
        cfg.get("max_parallel_postprocess"), DEFAULT_MAX_PARALLEL_POSTPROCESS
    )
    komga_base_url = cfg.get("komga_base_url")
    if not isinstance(komga_base_url, str) or not komga_base_url:
        komga_base_url = None
    komga_api_key = cfg.get("komga_api_key")
    if not isinstance(komga_api_key, str) or not komga_api_key:
        komga_api_key = None
    return AppConfigOut(
        postprocess_root=root,
        postprocess_default_output_dir=default,
        postprocess_known_output_dirs=known_str,
        postprocess_excluded_dir_names=excluded,
        delete_raw_after_pack=bool(cfg.get("delete_raw_after_pack", DEFAULT_DELETE_RAW)),
        default_watch_period=period,
        chapter_naming_template=chapter_template,
        default_reading_direction=reading_direction,
        max_parallel_postprocess=max_postprocess,
        komga_base_url=komga_base_url,
        komga_api_key=komga_api_key,
    )


def _coerce_clamped_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(1, min(value, 16))
    if isinstance(value, str):
        try:
            return max(1, min(int(value), 16))
        except ValueError:
            return default
    return default


@router.get("/config", operation_id="getConfig")
async def get_config(db: DbDep) -> AppConfigOut:
    return _load_config(await service.get_all(db))


@router.put("/config", operation_id="putConfig")
async def put_config(body: AppConfigIn, db: DbDep, bus: EventBusDep) -> AppConfigOut:
    root_raw = coerce_optional(body.postprocess_root)
    default_raw = coerce_optional(body.postprocess_default_output_dir)

    root_path = await validate_root(root_raw) if root_raw else None
    default_path = None
    if default_raw is not None:
        if root_path is None:
            raise DefaultOutputDirWithoutRoot()
        default_path = await validate_under_root(
            default_raw, root_path, field="postprocess_default_output_dir"
        )

    period_raw = coerce_optional(body.default_watch_period) or DEFAULT_WATCH_PERIOD
    try:
        parse_duration(period_raw)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    template_raw = coerce_optional(body.chapter_naming_template) or DEFAULT_CHAPTER_NAMING_TEMPLATE
    try:
        validate_chapter_naming_template(template_raw)
    except Exception as exc:
        raise BadRequestError(f"invalid chapter_naming_template: {exc}") from exc
    direction_raw = (
        coerce_optional(body.default_reading_direction) or DEFAULT_READING_DIRECTION
    ).lower()
    if direction_raw not in READING_DIRECTIONS:
        raise BadRequestError(
            f"invalid default_reading_direction: {direction_raw!r}; "
            f"expected one of {sorted(READING_DIRECTIONS)}"
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

    if body.postprocess_excluded_dir_names is None:
        existing_excluded = existing.get("postprocess_excluded_dir_names")
        excluded_norm = (
            existing_excluded
            if isinstance(existing_excluded, list)
            else list(DEFAULT_EXCLUDED_DIR_NAMES)
        )
    else:
        # Dedupe, strip, drop blanks; preserve order so the UI surfaces the
        # list back in the same shape the user typed it.
        seen: set[str] = set()
        excluded_norm = []
        for raw in body.postprocess_excluded_dir_names:
            cleaned = raw.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            excluded_norm.append(cleaned)

    max_post = _coerce_clamped_int(
        body.max_parallel_postprocess
        if body.max_parallel_postprocess is not None
        else existing.get("max_parallel_postprocess"),
        DEFAULT_MAX_PARALLEL_POSTPROCESS,
    )

    komga_base_url_raw = coerce_optional(body.komga_base_url)
    if komga_base_url_raw is not None:
        komga_base_url_raw = komga_base_url_raw.rstrip("/")
        if not (
            komga_base_url_raw.startswith("http://") or komga_base_url_raw.startswith("https://")
        ):
            raise BadRequestError("komga_base_url must start with http:// or https://")
    komga_api_key_raw = coerce_optional(body.komga_api_key)

    updates: dict[str, object] = {
        "postprocess_root": root_str,
        "postprocess_default_output_dir": str(default_path) if default_path else None,
        "postprocess_known_output_dirs": known,
        "postprocess_excluded_dir_names": excluded_norm,
        "delete_raw_after_pack": bool(body.delete_raw_after_pack),
        "default_watch_period": period_raw,
        "chapter_naming_template": template_raw,
        "default_reading_direction": direction_raw,
        "max_parallel_postprocess": max_post,
        "komga_base_url": komga_base_url_raw,
        "komga_api_key": komga_api_key_raw,
    }
    await service.set_many(db, updates)
    bus.publish(config_event())
    return _load_config(updates)
