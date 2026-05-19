"""Validation helpers for postprocess output dirs.

All output dirs are absolute paths that must live under a configured root
(e.g. `/mnt/nas/Media`). The helpers here turn a raw user-supplied string
into a resolved `Path`, creating it via `mkdir -p`, and raising HTTP 400
on every kind of bad input.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

_PROBE_NAME = ".gallery-dl-webui-write-probe"


def coerce_optional(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def validate_root(raw: str) -> Path:
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


def validate_under_root(
    raw: str, root: Path, *, field: str = "output_dir", create: bool = True
) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be an absolute path",
        )
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"cannot create {field}: {exc}") from exc
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be under root ({root_resolved})",
        )
    if create:
        _probe_writable(resolved, field)
    return resolved


def _probe_writable(path: Path, field: str) -> None:
    probe = path / _PROBE_NAME
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"{field} is not writable: {exc}") from exc
