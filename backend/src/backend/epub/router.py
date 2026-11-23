"""Per-series EPUB books: define chapter ranges, export, download.

Books are stored per target as chapter-number ranges; everything else
(which chapters a book holds, its metadata, whether its export is current)
is resolved against the CBZs on disk at request time, so the overview always
reflects the library as it is now.
"""

from __future__ import annotations

import asyncio
import logging
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from backend.app_config import service as app_config_service
from backend.app_config.constants import DEFAULT_READING_DIRECTION
from backend.comic_metadata import SERIES_JSON_NAME, read_series_json_metadata, sanitize
from backend.config import Settings
from backend.dependencies import DbDep, EventBusDep, SettingsDep
from backend.epub import service
from backend.epub.builder import build_epub
from backend.epub.exceptions import (
    EpubBookEmpty,
    EpubBookNotFound,
    EpubExportBusy,
    EpubExportFailed,
    EpubFileMissing,
)
from backend.epub.library import (
    BookPlan,
    BookRange,
    DiskChapter,
    StoredBook,
    book_chapters,
    build_series_context,
    plan_books,
    scan_series_chapters,
    suggest_ranges_from_volumes,
    validate_ranges,
)
from backend.epub.schemas import (
    EpubBookIn,
    EpubBookOut,
    EpubBooksIn,
    EpubChapterOut,
    EpubExportAllResult,
    EpubOverview,
)
from backend.events import epub_event
from backend.exceptions import BadRequestError
from backend.targets.dependencies import TargetDep
from backend.targets.schemas import Target

logger = logging.getLogger(__name__)

router = APIRouter(tags=["epub"])


def get_export_locks(request: Request) -> dict[int, asyncio.Lock]:
    # Per-app (not module-level) so each app instance — and each test's
    # event loop — gets its own locks.
    locks = getattr(request.app.state, "epub_export_locks", None)
    if locks is None:
        locks = {}
        request.app.state.epub_export_locks = locks
    return locks


ExportLocksDep = Annotated[dict[int, asyncio.Lock], Depends(get_export_locks)]


@dataclass(frozen=True)
class _SeriesState:
    export_dir: Path
    series_dir: Path | None
    chapters: list[DiskChapter]
    plans: list[BookPlan]
    suggestions: list[BookRange]


async def _load_state(target: Target, db: aiosqlite.Connection, settings: Settings) -> _SeriesState:
    cfg = await app_config_service.get_all(db)
    export_dir = app_config_service.epub_export_dir(cfg, settings.data_dir)
    default_out = cfg.get("postprocess_default_output_dir")
    output_dir = target.output_dir or (default_out if isinstance(default_out, str) else None)
    series_dir = Path(output_dir) / sanitize(target.name) if output_dir and target.name else None
    direction = cfg.get("default_reading_direction")
    default_direction = direction if isinstance(direction, str) else DEFAULT_READING_DIRECTION
    books = [b.to_stored() for b in await service.list_books(db, target.id)]
    return await asyncio.to_thread(
        _compute_state, target, series_dir, export_dir, books, default_direction
    )


def _compute_state(
    target: Target,
    series_dir: Path | None,
    export_dir: Path,
    books: list[StoredBook],
    default_direction: str,
) -> _SeriesState:
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
    return _SeriesState(
        export_dir=export_dir,
        series_dir=series_dir,
        chapters=chapters,
        plans=plan_books(ctx, books, chapters, export_dir),
        suggestions=suggest_ranges_from_volumes(chapters),
    )


def _overview(target: Target, state: _SeriesState) -> EpubOverview:
    position_by_path = {ch.path: plan.position for plan in state.plans for ch in plan.chapters}
    chapters = [
        EpubChapterOut(
            number=ch.number,
            title=ch.title,
            volume=ch.volume,
            pages=ch.pages,
            file_name=ch.path.name,
            book_position=position_by_path.get(ch.path),
        )
        for ch in state.chapters
    ]
    books = [
        EpubBookOut(
            id=plan.book_id,
            position=plan.position,
            title=plan.title,
            custom_title=plan.custom_title,
            chapter_start=plan.range.start,
            chapter_end=plan.range.end,
            chapter_count=len(plan.chapters),
            page_count=sum(ch.pages for ch in plan.chapters),
            first_chapter=plan.chapters[0].number if plan.chapters else None,
            last_chapter=plan.chapters[-1].number if plan.chapters else None,
            status=plan.status,
            exported_at=plan.exported_at if plan.file_exists else None,
            file_name=Path(plan.export_path).name
            if plan.file_exists and plan.export_path
            else None,
        )
        for plan in state.plans
    ]
    return EpubOverview(
        target_id=target.id,
        series=target.name,
        series_dir=str(state.series_dir) if state.series_dir is not None else None,
        export_dir=str(state.export_dir),
        chapters=chapters,
        books=books,
        unassigned=[ch.number for ch in chapters if ch.book_position is None],
        suggested_books=[
            EpubBookIn(chapter_start=r.start, chapter_end=r.end) for r in state.suggestions
        ],
    )


@asynccontextmanager
async def _exclusive(locks: dict[int, asyncio.Lock], target_id: int) -> AsyncIterator[None]:
    lock = locks.setdefault(target_id, asyncio.Lock())
    if lock.locked():
        raise EpubExportBusy()
    async with lock:
        yield


def _remove_stale_export(path: Path, export_dir: Path) -> None:
    """Best-effort removal of a book's previous export file after it moved."""
    try:
        if path.suffix == ".epub" and path.resolve().is_relative_to(export_dir.resolve()):
            path.unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove stale EPUB export %s", path, exc_info=True)


async def _export(
    db: aiosqlite.Connection, target: Target, plan: BookPlan, state: _SeriesState
) -> None:
    if plan.meta is None or plan.fingerprint is None or not plan.chapters:
        raise EpubBookEmpty()
    try:
        await asyncio.to_thread(build_epub, plan.path, plan.meta, book_chapters(plan.chapters))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        logger.exception("EPUB export failed: target=%s book=%s", target.id, plan.position)
        raise EpubExportFailed(f"EPUB export of {plan.title!r} failed: {exc}") from exc
    old = plan.export_path
    if old and old != str(plan.path):
        claimed = {p.export_path for p in state.plans if p.book_id != plan.book_id}
        if old not in claimed:
            await asyncio.to_thread(_remove_stale_export, Path(old), state.export_dir)
    await service.mark_exported(db, target.id, plan.book_id, str(plan.path), plan.fingerprint)


@router.get("/targets/{target_id}/epub", operation_id="getTargetEpub")
async def get_target_epub(target: TargetDep, db: DbDep, settings: SettingsDep) -> EpubOverview:
    """The series' packed chapters, its books, and each book's export status."""
    return _overview(target, await _load_state(target, db, settings))


@router.put("/targets/{target_id}/epub/books", operation_id="putTargetEpubBooks")
async def put_target_epub_books(
    body: EpubBooksIn,
    target: TargetDep,
    db: DbDep,
    settings: SettingsDep,
    bus: EventBusDep,
) -> EpubOverview:
    """Replace the series' book list. Books are re-numbered in chapter order."""
    entries = sorted(
        (
            (BookRange(b.chapter_start, b.chapter_end), (b.title or "").strip() or None)
            for b in body.books
        ),
        key=lambda e: e[0].start,
    )
    try:
        validate_ranges([rng for rng, _ in entries])
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    await service.replace_books(db, target.id, entries)
    bus.publish(epub_event(target.id))
    return _overview(target, await _load_state(target, db, settings))


@router.post(
    "/targets/{target_id}/epub/books/{book_id}/export", operation_id="exportTargetEpubBook"
)
async def export_target_epub_book(
    book_id: int,
    target: TargetDep,
    db: DbDep,
    settings: SettingsDep,
    bus: EventBusDep,
    locks: ExportLocksDep,
) -> EpubOverview:
    """(Re)build one book's EPUB into the export directory."""
    async with _exclusive(locks, target.id):
        state = await _load_state(target, db, settings)
        plan = next((p for p in state.plans if p.book_id == book_id), None)
        if plan is None:
            raise EpubBookNotFound()
        await _export(db, target, plan, state)
    bus.publish(epub_event(target.id))
    return _overview(target, await _load_state(target, db, settings))


@router.post("/targets/{target_id}/epub/export", operation_id="exportTargetEpubBooks")
async def export_target_epub_books(
    target: TargetDep,
    db: DbDep,
    settings: SettingsDep,
    bus: EventBusDep,
    locks: ExportLocksDep,
) -> EpubExportAllResult:
    """Export every book that was never exported or is outdated.

    One failing book doesn't stop the rest; failures are reported per book.
    """
    exported = 0
    errors: list[str] = []
    async with _exclusive(locks, target.id):
        state = await _load_state(target, db, settings)
        for plan in state.plans:
            if plan.status not in ("not_exported", "outdated"):
                continue
            try:
                await _export(db, target, plan, state)
            except EpubExportFailed as exc:
                errors.append(str(exc.detail))
            else:
                exported += 1
    if exported or errors:
        bus.publish(epub_event(target.id))
    return EpubExportAllResult(exported=exported, failed=len(errors), errors=errors)


@router.get(
    "/targets/{target_id}/epub/books/{book_id}/file",
    operation_id="downloadTargetEpubBook",
    response_class=FileResponse,
    responses={200: {"content": {"application/epub+zip": {}}}},
)
async def download_target_epub_book(book_id: int, target: TargetDep, db: DbDep) -> FileResponse:
    """The book's last exported EPUB file."""
    book = await service.get_book(db, target.id, book_id)
    if book is None:
        raise EpubBookNotFound()
    if not book.export_path:
        raise EpubFileMissing()
    path = Path(book.export_path)
    if not await asyncio.to_thread(path.is_file):
        raise EpubFileMissing()
    return FileResponse(path, media_type="application/epub+zip", filename=path.name)
