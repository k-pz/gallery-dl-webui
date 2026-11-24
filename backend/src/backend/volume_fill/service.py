"""Fill a series' missing chapter volumes from MangaDex.

Shared by the EPUB packer's "fill volumes" action, the download worker
(after each run) and the library-wide maintenance job. The volumes come from
gallery-dl's metadata pass against the series' MangaDex title page, which
reads MangaDex's chapter feed, so the same gallery-dl settings (language,
login, proxy) apply as for downloads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import aiosqlite

from backend.app_config import service as app_config_service
from backend.downloads.gallery import Gallery, MetadataResult
from backend.targets.paths import target_series_dir
from backend.targets.schemas import Target
from backend.volume_fill.library import (
    VolumeFillResult,
    chapters_missing_volume,
    fill_volumes,
    volume_source_url,
    volumes_by_number,
)


class NoVolumeSource(Exception):
    """The series has no MangaDex URL to read volumes from."""


class VolumeLookupFailed(Exception):
    """The metadata pass against the MangaDex page raised."""

    def __init__(self, source_url: str, cause: Exception) -> None:
        super().__init__(f"MangaDex lookup failed for {source_url}: {cause}")
        self.source_url = source_url


@dataclass
class TargetVolumeFill:
    source_url: str
    result: VolumeFillResult
    # False when nothing was missing, so MangaDex was not asked.
    looked_up: bool


async def fill_target_volumes(
    db: aiosqlite.Connection,
    gallery: Gallery,
    target: Target,
    *,
    known: Mapping[str, MetadataResult] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_step: Callable[[str], None] | None = None,
) -> TargetVolumeFill:
    """Fill the volumes the series' CBZs lack from its MangaDex page.

    The source is the series URL when it is a MangaDex title, else its
    metadata source URL. MangaDex is only asked when some chapter on disk
    lacks a volume; `known` holds metadata passes the caller already ran
    (keyed by URL), which are reused instead of fetching again.

    Raises NoVolumeSource when neither URL is a MangaDex title, and
    VolumeLookupFailed when the metadata pass raises.
    """
    source = volume_source_url(target.url, target.metadata_source_url)
    if source is None:
        raise NoVolumeSource()
    cfg = await app_config_service.get_all(db)
    series_dir = target_series_dir(target, cfg)
    if series_dir is None or not target.name:
        return TargetVolumeFill(source, VolumeFillResult(), looked_up=False)
    name = target.name
    chapters, missing = await asyncio.to_thread(chapters_missing_volume, series_dir, name)
    if not missing:
        return TargetVolumeFill(source, VolumeFillResult(chapters=chapters), looked_up=False)
    meta = (known or {}).get(source)
    if meta is None:
        try:
            meta = await asyncio.to_thread(gallery.extract_metadata, source)
        except Exception as exc:
            raise VolumeLookupFailed(source, exc) from exc
    volumes = volumes_by_number(meta.chapter_volumes)
    result = await asyncio.to_thread(
        fill_volumes,
        chapters,
        missing,
        volumes,
        should_cancel=should_cancel,
        on_step=on_step,
    )
    return TargetVolumeFill(source, result, looked_up=True)
