"""A series' EPUB state as it is on disk right now.

Shared by the EPUB endpoints and the series-stats refresher: both need the
chapters on disk, the stored books resolved against them, and the volume
suggestions. All filesystem work runs on a worker thread (series
directories often sit on a NAS mount).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from backend.app_config import service as app_config_service
from backend.app_config.constants import DEFAULT_READING_DIRECTION
from backend.comic_metadata import SERIES_JSON_NAME, read_series_json_metadata, sanitize
from backend.config import Settings
from backend.epub import service
from backend.epub.library import (
    BookPlan,
    DiskChapter,
    StoredBook,
    build_series_context,
    plan_books,
    scan_series_chapters,
    suggest_starts_from_volumes,
)
from backend.targets.schemas import Target


@dataclass(frozen=True)
class SeriesState:
    export_dir: Path
    series_dir: Path | None
    chapters: list[DiskChapter]
    plans: list[BookPlan]
    suggestions: list[float]


async def load_state(target: Target, db: aiosqlite.Connection, settings: Settings) -> SeriesState:
    cfg = await app_config_service.get_all(db)
    export_dir = app_config_service.epub_export_dir(cfg, settings.data_dir)
    default_out = cfg.get("postprocess_default_output_dir")
    output_dir = target.output_dir or (default_out if isinstance(default_out, str) else None)
    series_dir = Path(output_dir) / sanitize(target.name) if output_dir and target.name else None
    direction = cfg.get("default_reading_direction")
    default_direction = direction if isinstance(direction, str) else DEFAULT_READING_DIRECTION
    books = [b.to_stored() for b in await service.list_books(db, target.id)]
    return await asyncio.to_thread(
        compute_state, target, series_dir, export_dir, books, default_direction
    )


def compute_state(
    target: Target,
    series_dir: Path | None,
    export_dir: Path,
    books: list[StoredBook],
    default_direction: str,
) -> SeriesState:
    chapters: list[DiskChapter] = []
    series_json: dict[str, object] = {}
    if series_dir is not None and target.name:
        chapters = scan_series_chapters(series_dir, target.name)
        series_json = read_series_json_metadata(series_dir / SERIES_JSON_NAME) or {}
    ctx = (
        build_series_context(
            name=target.name,
            url=target.url,
            series_json=series_json,
            chapters=chapters,
            target_tags=target.tags,
            target_reading_direction=target.reading_direction,
            default_reading_direction=default_direction,
        )
        if target.name
        else None
    )
    return SeriesState(
        export_dir=export_dir,
        series_dir=series_dir,
        chapters=chapters,
        plans=plan_books(ctx, books, chapters, export_dir),
        suggestions=suggest_starts_from_volumes(chapters),
    )
