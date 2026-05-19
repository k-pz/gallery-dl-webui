"""Export/import the library (targets + watch state) as YAML.

The schema is intentionally tiny so a human can hand-edit a file before
re-importing: one `series:` list, one entry per target. Anything we don't
know how to round-trip (download history, status, IDs) is omitted.

Round-trip example::

    version: 1
    series:
      - url: https://example.com/manga/abc
        name: ABC Series
        extractor: manganato
        output_dir: /mnt/nas/Media/Manga
        watch:
          enabled: true
          period: 1d
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from backend.api.deps import PollerDep, StorageDep
from backend.api.schemas import LibraryImportResult
from backend.durations import parse_duration
from backend.output_dirs import validate_under_root
from backend.storage import Target

router = APIRouter(tags=["library"])

SCHEMA_VERSION = 1


def _series_to_dict(target: Target) -> dict[str, Any]:
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


@router.get("/library/export", operation_id="exportLibrary", response_class=PlainTextResponse)
async def export_library(storage: StorageDep) -> PlainTextResponse:
    summaries = await storage.list_targets()
    payload = {
        "version": SCHEMA_VERSION,
        "series": [_series_to_dict(s.target) for s in summaries],
    }
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return PlainTextResponse(content=body, media_type="application/yaml")


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


async def _parse_yaml_body(request: Request) -> Any:
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="request body is empty")
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"invalid YAML: {exc}") from exc


@router.post("/library/import", operation_id="importLibrary")
async def import_library(
    request: Request, storage: StorageDep, poller: PollerDep
) -> LibraryImportResult:
    parsed = await _parse_yaml_body(request)
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="top-level YAML must be a mapping")
    version = parsed.get("version")
    if version not in (None, SCHEMA_VERSION):
        raise HTTPException(status_code=400, detail=f"unsupported schema version: {version!r}")
    series = parsed.get("series")
    if not isinstance(series, list):
        raise HTTPException(status_code=400, detail="'series' must be a list")

    cfg = await storage.get_app_config()
    root_raw = cfg.get("postprocess_root")
    root: Path | None = Path(root_raw) if isinstance(root_raw, str) and root_raw else None

    imported = 0
    updated = 0
    errors: list[str] = []
    notified = False
    for idx, raw_item in enumerate(series):
        if not isinstance(raw_item, dict):
            errors.append(f"series[{idx}]: must be a mapping")
            continue
        item = cast(dict[str, Any], raw_item)
        url = _coerce_str(item.get("url"))
        if not url:
            errors.append(f"series[{idx}]: 'url' is required")
            continue
        name = _coerce_str(item.get("name"))
        extractor = _coerce_str(item.get("extractor"))
        output_dir_raw = _coerce_str(item.get("output_dir"))
        output_dir: str | None = None
        if output_dir_raw is not None:
            if root is None:
                errors.append(
                    f"series[{idx}] ({url}): output_dir requires postprocess_root to be set"
                )
                continue
            # Pre-check that the path is under root before calling
            # validate_under_root, which mkdirs as a side effect.
            try:
                candidate = Path(output_dir_raw).resolve()
            except OSError as exc:
                errors.append(f"series[{idx}] ({url}): bad output_dir: {exc}")
                continue
            root_resolved = root.resolve()
            if candidate != root_resolved and root_resolved not in candidate.parents:
                errors.append(
                    f"series[{idx}] ({url}): output_dir must be under root ({root_resolved})"
                )
                continue
            try:
                output_dir = str(validate_under_root(output_dir_raw, root, field="output_dir"))
            except HTTPException as exc:
                errors.append(f"series[{idx}] ({url}): {exc.detail}")
                continue

        raw_watch = item.get("watch")
        watched = False
        watch_period: str | None = None
        if isinstance(raw_watch, dict):
            watch_raw = cast(dict[str, Any], raw_watch)
            watched = _coerce_bool(watch_raw.get("enabled"))
            period_raw = _coerce_str(watch_raw.get("period"))
            if period_raw is not None:
                try:
                    parse_duration(period_raw)
                except ValueError as exc:
                    errors.append(f"series[{idx}] ({url}): invalid watch.period: {exc}")
                    continue
                watch_period = period_raw

        existing = await storage.get_target_by_url(url)
        target = await storage.upsert_target(url, extractor, output_dir)
        if existing is None:
            imported += 1
        else:
            updated += 1
        if name:
            await storage.set_target_name(target.id, name)
        await storage.update_target(
            target.id,
            watched=watched,
            watch_period=watch_period,
            output_dir=output_dir,
        )
        if watched:
            notified = True

    if notified:
        poller.notify()

    return LibraryImportResult(imported=imported, updated=updated, errors=errors)
