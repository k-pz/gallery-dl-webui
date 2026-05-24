"""Export/import the library (targets + watch state) as YAML.

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

from backend.app_config import service as app_config_service
from backend.app_config.constants import READING_DIRECTIONS
from backend.dependencies import DbDep
from backend.downloads.postprocess import SERIES_STATUSES, normalize_tags
from backend.exceptions import BadRequestError
from backend.library import service
from backend.library.constants import SCHEMA_VERSION
from backend.library.schemas import LibraryImportResult
from backend.output_dirs.utils import validate_under_root
from backend.targets import service as targets_service
from backend.targets.dependencies import PollerDep
from backend.targets.utils import parse_duration

router = APIRouter(tags=["library"])


@router.get("/library/export", operation_id="exportLibrary", response_class=PlainTextResponse)
async def export_library(db: DbDep) -> PlainTextResponse:
    summaries = await targets_service.list_all(db)
    payload = {
        "version": SCHEMA_VERSION,
        "series": [service.series_to_dict(s.target) for s in summaries],
    }
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return PlainTextResponse(content=body, media_type="application/yaml")


async def _parse_yaml_body(request: Request) -> Any:
    raw = await request.body()
    if not raw:
        raise BadRequestError("request body is empty")
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise BadRequestError(f"invalid YAML: {exc}") from exc


@router.post("/library/import", operation_id="importLibrary")
async def import_library(request: Request, db: DbDep, poller: PollerDep) -> LibraryImportResult:
    parsed = await _parse_yaml_body(request)
    if not isinstance(parsed, dict):
        raise BadRequestError("top-level YAML must be a mapping")
    version = parsed.get("version")
    if version not in (None, SCHEMA_VERSION):
        raise BadRequestError(f"unsupported schema version: {version!r}")
    series = parsed.get("series")
    if not isinstance(series, list):
        raise BadRequestError("'series' must be a list")

    cfg = await app_config_service.get_all(db)
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
        url = service.coerce_str(item.get("url"))
        if not url:
            errors.append(f"series[{idx}]: 'url' is required")
            continue
        name = service.coerce_str(item.get("name"))
        extractor = service.coerce_str(item.get("extractor"))
        output_dir_raw = service.coerce_str(item.get("output_dir"))
        output_dir: str | None = None
        if output_dir_raw is not None:
            if root is None:
                errors.append(
                    f"series[{idx}] ({url}): output_dir requires postprocess_root to be set"
                )
                continue
            # Two-phase: validate (no mkdir) first so a bad path doesn't leave a
            # stray directory behind, then create + probe.
            try:
                validate_under_root(output_dir_raw, root, field="output_dir", create=False)
                output_dir = str(validate_under_root(output_dir_raw, root, field="output_dir"))
            except HTTPException as exc:
                errors.append(f"series[{idx}] ({url}): {exc.detail}")
                continue

        raw_watch = item.get("watch")
        watched = False
        watch_period: str | None = None
        if isinstance(raw_watch, dict):
            watch_raw = cast(dict[str, Any], raw_watch)
            watched = service.coerce_bool(watch_raw.get("enabled"))
            period_raw = service.coerce_str(watch_raw.get("period"))
            if period_raw is not None:
                try:
                    parse_duration(period_raw)
                except ValueError as exc:
                    errors.append(f"series[{idx}] ({url}): invalid watch.period: {exc}")
                    continue
                watch_period = period_raw

        raw_tags = item.get("tags")
        tags: list[str] | None = None
        if isinstance(raw_tags, list):
            tags = normalize_tags([t for t in raw_tags if isinstance(t, str)])
        reading_direction_raw = service.coerce_str(item.get("reading_direction"))
        reading_direction: str | None = None
        if reading_direction_raw is not None:
            cleaned = reading_direction_raw.lower()
            if cleaned not in READING_DIRECTIONS:
                errors.append(
                    f"series[{idx}] ({url}): invalid reading_direction: {reading_direction_raw!r}"
                )
                continue
            reading_direction = cleaned
        series_status_raw = service.coerce_str(item.get("series_status"))
        series_status: str | None = None
        if series_status_raw is not None:
            if series_status_raw not in SERIES_STATUSES:
                errors.append(
                    f"series[{idx}] ({url}): invalid series_status: {series_status_raw!r}"
                )
                continue
            series_status = series_status_raw

        existing = await targets_service.get_by_url(db, url)
        target = await targets_service.upsert(db, url, extractor, output_dir)
        if existing is None:
            imported += 1
        else:
            updated += 1
        if name:
            await targets_service.set_name(db, target.id, name)
        await targets_service.update(
            db,
            target.id,
            watched=watched,
            watch_period=watch_period,
            output_dir=output_dir,
            tags=tags,
            reading_direction=reading_direction,
            series_status=series_status,
        )
        if watched:
            notified = True

    if notified:
        poller.notify()

    return LibraryImportResult(imported=imported, updated=updated, errors=errors)
