"""Validation helpers for postprocess output dirs.

All output dirs are absolute paths that must live under a configured root
(e.g. `/mnt/nas/Media`). The helpers here turn a raw user-supplied string
into a resolved `Path`, creating it via `mkdir -p`, and raising HTTP 400
on every kind of bad input.

These helpers are imported by every domain that accepts user-supplied paths
(downloads, targets, library, app_config), not just the output_dirs router.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import HTTPException

_PROBE_NAME = ".gallery-dl-webui-write-probe"


def coerce_optional(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


async def validate_root(raw: str) -> Path:
    """Async front for `_validate_root_sync`.

    The mkdir + write-probe regularly target a NAS mount; a hung mount must
    stall only the request's worker thread, never the event loop.
    """
    return await asyncio.to_thread(_validate_root_sync, raw)


async def validate_under_root(
    raw: str, root: Path, *, field: str = "output_dir", create: bool = True
) -> Path:
    """Async front for `_validate_under_root_sync` — same NAS caveat as above."""
    return await asyncio.to_thread(_validate_under_root_sync, raw, root, field=field, create=create)


def _validate_root_sync(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="postprocess_root must be an absolute path",
        )
    parent = path.parent
    if not parent.exists():
        raise HTTPException(
            status_code=400,
            detail=f"root parent directory does not exist: {parent}",
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"cannot create root: {exc}") from exc
    _probe_writable(path, "root")
    return path.resolve()


def _validate_under_root_sync(
    raw: str, root: Path, *, field: str = "output_dir", create: bool = True
) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be an absolute path",
        )
    # Containment before any filesystem writes: a rejected request must not
    # leave a stray directory tree behind outside the root. resolve() is
    # non-strict, so this works for paths that don't exist yet.
    resolved = path.resolve()
    root_resolved = root.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be under root ({root_resolved})",
        )
    if create:
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"cannot create {field}: {exc}") from exc
        _probe_writable(resolved, field)
    return resolved


def _probe_writable(path: Path, field: str) -> None:
    probe = path / _PROBE_NAME
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"{field} is not writable: {exc}") from exc
