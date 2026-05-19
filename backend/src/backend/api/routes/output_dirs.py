"""Listing and creation of output sub-directories under postprocess_root.

By design the picker only ever surfaces *direct children* of the configured
root: a series-level folder like `/mnt/nas/Media/Manga`, never a per-series
subdir like `/mnt/nas/Media/Manga/SomeSeries`. The packing step writes the
series subdirectory itself, so suggesting deeper paths would only let users
pick a destination that doesn't make sense.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.api.deps import StorageDep
from backend.api.schemas import DirCreate, DirEntry
from backend.output_dirs import validate_under_root

router = APIRouter(tags=["output_dirs"])

MAX_ENTRIES = 500


async def _resolve_root(storage) -> Path:
    cfg = await storage.get_app_config()
    root_raw = cfg.get("postprocess_root")
    if not isinstance(root_raw, str) or not root_raw:
        raise HTTPException(status_code=400, detail="postprocess_root is not configured")
    return Path(root_raw)


def _list_direct_children(root: Path) -> list[DirEntry]:
    """Return non-hidden first-level subdirectories of root."""
    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    entries: list[DirEntry] = []
    for child in children:
        if child.name.startswith("."):
            continue
        entries.append(DirEntry(path=str(child), name=child.name, depth=1))
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


@router.get("/output-dirs", operation_id="listOutputDirs")
async def list_output_dirs(storage: StorageDep) -> list[DirEntry]:
    root = await _resolve_root(storage)
    if not root.is_dir():
        return []
    return _list_direct_children(root)


@router.post("/output-dirs", operation_id="createOutputDir")
async def create_output_dir(body: DirCreate, storage: StorageDep) -> DirEntry:
    root = await _resolve_root(storage)
    raw = body.path.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    raw_path = Path(raw)
    # The picker only ever creates direct children of the root, so we accept
    # either a single relative segment ("manga") or an absolute path whose
    # final component sits directly under root ("/mnt/nas/Media/manga"). We
    # validate the depth before delegating to validate_under_root so a deeper
    # rejected path doesn't leave a stray directory on disk.
    if raw_path.is_absolute():
        root_resolved = root.resolve()
        parent_resolved = raw_path.parent.resolve()
        if parent_resolved != root_resolved:
            raise HTTPException(
                status_code=400,
                detail=f"path must be a direct child of root ({root_resolved})",
            )
        target = raw_path
    else:
        cleaned = raw.strip("/")
        if "/" in cleaned or cleaned in ("", ".", ".."):
            raise HTTPException(
                status_code=400,
                detail="path must be a single folder name (no separators)",
            )
        target = root / cleaned
    resolved = validate_under_root(str(target), root, field="path")
    return DirEntry(path=str(resolved), name=resolved.name, depth=1)
