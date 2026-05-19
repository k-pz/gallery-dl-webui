"""Serialise targets to/from the YAML library format.

The schema is intentionally tiny so a human can hand-edit a file before
re-importing: one `series:` list, one entry per target. Anything we don't
know how to round-trip (download history, status, IDs) is omitted.
"""

from __future__ import annotations

from typing import Any

from backend.targets.models import Target


def series_to_dict(target: Target) -> dict[str, Any]:
    out: dict[str, Any] = {"url": target.url}
    if target.name:
        out["name"] = target.name
    if target.extractor:
        out["extractor"] = target.extractor
    if target.output_dir:
        out["output_dir"] = target.output_dir
    watch: dict[str, Any] = {"enabled": bool(target.watched)}
    if target.watch_period:
        watch["period"] = target.watch_period
    out["watch"] = watch
    return out


def coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default
