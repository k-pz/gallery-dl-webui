from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter

from backend.dependencies import DbDep
from backend.exceptions import BadRequestError
from backend.output_dirs import service
from backend.output_dirs.schemas import DirCreate, DirEntry
from backend.output_dirs.utils import validate_under_root

router = APIRouter(tags=["output_dirs"])


@router.get("/output-dirs", operation_id="listOutputDirs")
async def list_output_dirs(db: DbDep) -> list[DirEntry]:
    root = await service.resolve_root(db)
    if not root.is_dir():
        return []
    excluded = await service.resolve_excluded_dir_names(db)
    # iterdir against a NAS mount — keep it off the event loop.
    return await asyncio.to_thread(service.list_direct_children, root, excluded=excluded)


@router.post("/output-dirs", operation_id="createOutputDir")
async def create_output_dir(body: DirCreate, db: DbDep) -> DirEntry:
    root = await service.resolve_root(db)
    raw = body.path.strip()
    if not raw:
        raise BadRequestError("path is required")
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
            raise BadRequestError(f"path must be a direct child of root ({root_resolved})")
        target = raw_path
    else:
        cleaned = raw.strip("/")
        if "/" in cleaned or cleaned in ("", ".", ".."):
            raise BadRequestError("path must be a single folder name (no separators)")
        target = root / cleaned
    resolved = await validate_under_root(str(target), root, field="path")
    return DirEntry(path=str(resolved), name=resolved.name, depth=1)
