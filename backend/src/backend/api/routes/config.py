from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.api.deps import StorageDep
from backend.api.schemas import AppConfigIn, AppConfigOut

router = APIRouter(tags=["config"])

DEFAULT_DELETE_RAW = True
_PROBE_NAME = ".gallery-dl-webui-write-probe"


def _coerce_dir(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _validate_output_dir(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="postprocess_output_dir must be an absolute path",
        )
    parent = path.parent
    if not parent.exists():
        raise HTTPException(
            status_code=400,
            detail=f"parent directory does not exist: {parent}",
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"cannot create output directory: {exc}"
        ) from exc
    probe = path / _PROBE_NAME
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"output directory is not writable: {exc}"
        ) from exc
    return path


@router.get("/config", operation_id="getConfig")
async def get_config(storage: StorageDep) -> AppConfigOut:
    cfg = await storage.get_app_config()
    return AppConfigOut(
        postprocess_output_dir=cfg.get("postprocess_output_dir"),
        delete_raw_after_pack=bool(cfg.get("delete_raw_after_pack", DEFAULT_DELETE_RAW)),
    )


@router.put("/config", operation_id="putConfig")
async def put_config(body: AppConfigIn, storage: StorageDep) -> AppConfigOut:
    output_dir = _coerce_dir(body.postprocess_output_dir)
    if output_dir is not None:
        _validate_output_dir(output_dir)
    await storage.set_app_config(
        {
            "postprocess_output_dir": output_dir,
            "delete_raw_after_pack": bool(body.delete_raw_after_pack),
        }
    )
    return AppConfigOut(
        postprocess_output_dir=output_dir,
        delete_raw_after_pack=bool(body.delete_raw_after_pack),
    )
