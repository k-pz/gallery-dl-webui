"""Listing and creation of output sub-directories under postprocess_root."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.api.deps import StorageDep
from backend.api.schemas import DirCreate, DirEntry
from backend.output_dirs import validate_under_root

router = APIRouter(tags=["output_dirs"])

MAX_DEPTH = 3
MAX_ENTRIES = 500


async def _resolve_root(storage) -> Path:
    cfg = await storage.get_app_config()
    root_raw = cfg.get("postprocess_root")
    if not isinstance(root_raw, str) or not root_raw:
        raise HTTPException(status_code=400, detail="postprocess_root is not configured")
    return Path(root_raw)


def _walk(root: Path) -> list[DirEntry]:
    """Walk up to MAX_DEPTH levels under root. Skip hidden dirs."""
    entries: list[DirEntry] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        if len(entries) >= MAX_ENTRIES:
            break
        path, depth = stack.pop()
        if depth >= MAX_DEPTH:
            continue
        try:
            children = sorted(p for p in path.iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            entries.append(DirEntry(path=str(child), name=child.name, depth=depth + 1))
            stack.append((child, depth + 1))
            if len(entries) >= MAX_ENTRIES:
                break
    entries.sort(key=lambda e: e.path)
    return entries


@router.get("/output-dirs", operation_id="listOutputDirs")
async def list_output_dirs(storage: StorageDep) -> list[DirEntry]:
    root = await _resolve_root(storage)
    if not root.is_dir():
        return []
    return _walk(root)


@router.post("/output-dirs", operation_id="createOutputDir")
async def create_output_dir(body: DirCreate, storage: StorageDep) -> DirEntry:
    root = await _resolve_root(storage)
    raw = body.path.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    # Allow either absolute paths or paths relative to root.
    p = Path(raw)
    if not p.is_absolute():
        p = root / raw.lstrip("/")
    resolved = validate_under_root(str(p), root, field="path")
    return DirEntry(
        path=str(resolved),
        name=resolved.name,
        depth=len(resolved.relative_to(root.resolve()).parts),
    )
