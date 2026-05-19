from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.deps import StorageDep
from backend.api.schemas import AppConfigIn, AppConfigOut
from backend.durations import parse_duration
from backend.output_dirs import coerce_optional, validate_root, validate_under_root

router = APIRouter(tags=["config"])

DEFAULT_DELETE_RAW = True
DEFAULT_WATCH_PERIOD = "1d"


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
    return AppConfigOut(
        postprocess_root=root,
        postprocess_default_output_dir=default,
        postprocess_known_output_dirs=known_str,
        delete_raw_after_pack=bool(cfg.get("delete_raw_after_pack", DEFAULT_DELETE_RAW)),
        default_watch_period=period,
    )


@router.get("/config", operation_id="getConfig")
async def get_config(storage: StorageDep) -> AppConfigOut:
    return _load_config(await storage.get_app_config())


@router.put("/config", operation_id="putConfig")
async def put_config(body: AppConfigIn, storage: StorageDep) -> AppConfigOut:
    root_raw = coerce_optional(body.postprocess_root)
    default_raw = coerce_optional(body.postprocess_default_output_dir)

    root_path = validate_root(root_raw) if root_raw else None
    default_path = None
    if default_raw is not None:
        if root_path is None:
            raise HTTPException(
                status_code=400,
                detail="postprocess_default_output_dir requires postprocess_root",
            )
        default_path = validate_under_root(
            default_raw, root_path, field="postprocess_default_output_dir"
        )

    period_raw = coerce_optional(body.default_watch_period) or DEFAULT_WATCH_PERIOD
    try:
        parse_duration(period_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # When the root changes, drop the remembered dirs — they may no longer be valid.
    existing = await storage.get_app_config()
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
    }
    await storage.set_app_config(updates)
    return _load_config(updates)
