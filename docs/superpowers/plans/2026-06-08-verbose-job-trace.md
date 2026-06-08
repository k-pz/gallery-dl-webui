# Verbose Per-Job Download Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a structured per-job download trace (discovered / needed / downloaded / failed counts + per-chapter outcome with pages, title, date, and failure reason) so the past-job screen shows what actually happened instead of stamping every chapter "completed".

**Architecture:** Extend the existing `download_files` table (already one row per chapter) with outcome columns, add two count columns to `downloads`, capture per-chapter failure reasons via a thread-scoped logging handler attached around gallery-dl's `job.run()`, reconcile `FileRecord`s → outcomes at job finish, and make the progress endpoint read persisted rows for terminal jobs. The frontend `ProgressCard` renders the persisted truth.

**Tech Stack:** Backend — FastAPI, aiosqlite (SQLite), gallery-dl Python API, pytest, ruff, ty. Frontend — React 19, Mantine, TanStack Query, hey-api generated client, vitest, biome.

**Toolchain note:** All commands go through `mise`. Backend one-offs: `cd backend && uv run <cmd>`. Frontend one-offs: `cd frontend && pnpm <cmd>`. Never invoke `python`/`pytest`/`node` directly.

---

## Reference: shapes used across tasks

These names/types are introduced in early tasks and reused later — keep them consistent:

- `ChapterSeed` (dataclass, `backend/src/backend/downloads/outcomes.py`): `name: str`, `date: str`. The needed chapter + its discovered date.
- `ChapterOutcome` (dataclass, same file): `name: str`, `status: ChapterOutcomeStatus`, `pages: int`, `title: str`, `date: str`, `error: str | None`.
- `ChapterOutcomeStatus = Literal["downloaded", "skipped", "failed"]`.
- `reconcile_outcomes(needed, records, chapter_errors, exit_code) -> list[ChapterOutcome]`.
- `ChapterErrorCollector(logging.Handler)` (`backend/src/backend/downloads/capture.py`): ctor `(chapter_ctx: list[str], thread_id: int)`, attribute `errors: dict[str, str]`.
- `Gallery.run_download(...) -> tuple[int, list[FileRecord], dict[str, str]]` (was 2-tuple; third element is `chapter_errors`).
- `service.save_manifest(db, id, chapter_names, *, dates=None, discovered=None)` (added kwargs).
- `service.save_chapter_outcomes(db, id, outcomes)` / `service.get_chapter_outcomes(db, id) -> list[ChapterOutcome]`.
- New `downloads` columns: `chapters_discovered INTEGER`, `chapters_failed INTEGER`.
- New `download_files` columns: `status TEXT`, `pages INTEGER`, `title TEXT`, `date TEXT`, `error TEXT`.

---

## Task 1: Add the new DB columns (schema + migration)

**Files:**
- Modify: `backend/src/backend/database.py` (SCHEMA strings ~33-63, `_migrate` ~112-133)
- Test: `backend/tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_database.py`:

```python
async def test_migrate_adds_verbose_trace_columns(tmp_path) -> None:
    from backend.database import open_database

    db = await open_database(tmp_path / "jobs.db")
    try:
        async with db.execute("PRAGMA table_info(downloads)") as cur:
            dl_cols = {r["name"] for r in await cur.fetchall()}
        async with db.execute("PRAGMA table_info(download_files)") as cur:
            df_cols = {r["name"] for r in await cur.fetchall()}
    finally:
        await db.close()

    assert {"chapters_discovered", "chapters_failed"} <= dl_cols
    assert {"status", "pages", "title", "date", "error"} <= df_cols


async def test_migrate_is_idempotent_on_existing_db(tmp_path) -> None:
    from backend.database import open_database

    path = tmp_path / "jobs.db"
    db = await open_database(path)
    await db.close()
    # Re-open: _migrate runs again over a DB that already has the columns.
    db = await open_database(path)
    try:
        async with db.execute("PRAGMA table_info(download_files)") as cur:
            df_cols = {r["name"] for r in await cur.fetchall()}
    finally:
        await db.close()
    assert "status" in df_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_database.py::test_migrate_adds_verbose_trace_columns -v`
Expected: FAIL — assertion error, columns missing.

- [ ] **Step 3: Update SCHEMA for fresh DBs**

In `database.py`, change the `downloads` CREATE TABLE to include the two new columns (add after `chapters_total INTEGER,`):

```sql
    chapters_total INTEGER,
    chapters_discovered INTEGER,
    chapters_failed INTEGER,
```

Change the `download_files` CREATE TABLE to:

```sql
CREATE TABLE IF NOT EXISTS download_files (
    download_id INTEGER NOT NULL REFERENCES downloads(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    relpath TEXT NOT NULL,
    status TEXT,
    pages INTEGER,
    title TEXT,
    date TEXT,
    error TEXT,
    PRIMARY KEY (download_id, idx)
);
```

- [ ] **Step 4: Add migration ALTERs for existing DBs**

In `_migrate`, inside the `downloads` column block (after the `chapters_total` check), add:

```python
    if "chapters_discovered" not in cols:
        await db.execute("ALTER TABLE downloads ADD COLUMN chapters_discovered INTEGER")
    if "chapters_failed" not in cols:
        await db.execute("ALTER TABLE downloads ADD COLUMN chapters_failed INTEGER")
```

After the `downloads` block (before the `targets` PRAGMA block), add a new `download_files` migration block:

```python
    async with db.execute("PRAGMA table_info(download_files)") as cur:
        df_cols = {row["name"] for row in await cur.fetchall()}
    for col, decl in (
        ("status", "TEXT"),
        ("pages", "INTEGER"),
        ("title", "TEXT"),
        ("date", "TEXT"),
        ("error", "TEXT"),
    ):
        if col not in df_cols:
            await db.execute(f"ALTER TABLE download_files ADD COLUMN {col} {decl}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_database.py -v`
Expected: PASS (including the two new tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/backend/database.py backend/tests/test_database.py
git commit -m "feat(db): add verbose per-job trace columns"
```

---

## Task 2: Pydantic schema fields (Download, ChapterProgress, ProgressOut)

**Files:**
- Modify: `backend/src/backend/downloads/schemas.py`
- Test: `backend/tests/downloads/test_service.py` (Download round-trips new fields via existing `get`)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/downloads/test_service.py`:

```python
async def test_download_schema_exposes_new_count_fields(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    fetched = await service.get(db, d.id)
    assert fetched is not None
    # New optional fields default to None on a fresh row.
    assert fetched.chapters_discovered is None
    assert fetched.chapters_failed is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_service.py::test_download_schema_exposes_new_count_fields -v`
Expected: FAIL — `AttributeError`/validation: `chapters_discovered` not a field.

- [ ] **Step 3: Add fields to the Pydantic models**

In `schemas.py`, in `class Download`, add after `chapters_total`:

```python
    chapters_total: int | None
    chapters_discovered: int | None = None
    chapters_failed: int | None = None
```

Replace `class ChapterProgress` with:

```python
class ChapterProgress(BaseModel):
    name: str
    files_total: int
    files_present: int
    stage: str
    status: str | None = None
    pages: int | None = None
    title: str | None = None
    date: str | None = None
    error: str | None = None
```

Replace `class ProgressOut` with:

```python
class ProgressOut(BaseModel):
    status: str
    files_expected: int | None
    files_present: int
    chapters_discovered: int | None = None
    chapters_needed: int | None = None
    chapters_downloaded: int = 0
    chapters_failed: int = 0
    chapters_skipped: int = 0
    chapters: list[ChapterProgress]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/downloads/test_service.py::test_download_schema_exposes_new_count_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/backend/downloads/schemas.py backend/tests/downloads/test_service.py
git commit -m "feat(downloads): add verbose-trace fields to schemas"
```

---

## Task 3: Outcome reconciliation (pure logic)

**Files:**
- Create: `backend/src/backend/downloads/outcomes.py`
- Test: `backend/tests/downloads/test_outcomes.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/downloads/test_outcomes.py`:

```python
from pathlib import Path

from backend.downloads.outcomes import ChapterSeed, reconcile_outcomes
from backend.downloads.postprocess import FileRecord


def _rec(chapter: str, name: str, *, title: str = "", date: str = "") -> FileRecord:
    return FileRecord(
        category="fake",
        manga="S",
        chapter=chapter,
        title=title,
        volume="",
        lang="",
        author="",
        date=date,
        path=Path(f"/dl/S/c{chapter}/{name}"),
    )


def test_downloaded_chapter_counts_image_pages_and_keeps_metadata() -> None:
    needed = [ChapterSeed(name="1", date="2026-01-01")]
    records = [
        _rec("1", "001.jpg", title="Intro", date="2026-01-02"),
        _rec("1", "002.jpg"),
        _rec("1", "thumb.txt"),  # non-image, not counted as a page
    ]
    out = reconcile_outcomes(needed, records, {}, exit_code=0)
    assert len(out) == 1
    assert out[0].name == "1"
    assert out[0].status == "downloaded"
    assert out[0].pages == 2
    assert out[0].title == "Intro"
    assert out[0].date == "2026-01-02"
    assert out[0].error is None


def test_needed_chapter_with_error_is_failed_with_reason() -> None:
    needed = [ChapterSeed(name="7", date="")]
    out = reconcile_outcomes(needed, [], {"7": "403 Forbidden"}, exit_code=1)
    assert out[0].status == "failed"
    assert out[0].error == "403 Forbidden"


def test_needed_chapter_no_records_clean_exit_is_skipped() -> None:
    needed = [ChapterSeed(name="3", date="2026-03-03")]
    out = reconcile_outcomes(needed, [], {}, exit_code=0)
    assert out[0].status == "skipped"
    assert out[0].date == "2026-03-03"
    assert out[0].error is None


def test_needed_chapter_no_records_dirty_exit_is_failed() -> None:
    needed = [ChapterSeed(name="3", date="")]
    out = reconcile_outcomes(needed, [], {}, exit_code=1)
    assert out[0].status == "failed"


def test_records_for_unlisted_chapter_are_synthesized() -> None:
    # Date-less extractor: manifest was empty but files still downloaded.
    out = reconcile_outcomes([], [_rec("9", "001.jpg")], {}, exit_code=0)
    assert len(out) == 1
    assert out[0].name == "9"
    assert out[0].status == "downloaded"
    assert out[0].pages == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_outcomes.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.downloads.outcomes`.

- [ ] **Step 3: Implement `outcomes.py`**

Create `backend/src/backend/downloads/outcomes.py`:

```python
"""Reconcile a download's needed chapters + emitted FileRecords + captured
per-chapter errors into a persistable per-chapter outcome list.

Pure functions only — no DB, no gallery-dl. Tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.downloads.postprocess import IMAGE_SUFFIXES, FileRecord

ChapterOutcomeStatus = Literal["downloaded", "skipped", "failed"]


@dataclass(frozen=True)
class ChapterSeed:
    """A needed chapter discovered by the metadata pass."""

    name: str
    date: str


@dataclass(frozen=True)
class ChapterOutcome:
    name: str
    status: ChapterOutcomeStatus
    pages: int
    title: str
    date: str
    error: str | None


def _pages(records: list[FileRecord]) -> int:
    return sum(1 for r in records if r.path.suffix.lower() in IMAGE_SUFFIXES)


def _first(values: list[str], fallback: str = "") -> str:
    return next((v for v in values if v), fallback)


def reconcile_outcomes(
    needed: list[ChapterSeed],
    records: list[FileRecord],
    chapter_errors: dict[str, str],
    exit_code: int,
) -> list[ChapterOutcome]:
    """Map each needed chapter (and any unlisted-but-downloaded chapter) to a
    concrete outcome.

    - records present  -> downloaded (pages/title/date from records)
    - error captured   -> failed (with reason)
    - clean exit, none -> skipped (gallery-dl archive already had the files)
    - dirty exit, none -> failed (reason unknown)
    Chapters that produced records but weren't in `needed` (date-less
    extractors) are appended as downloaded so the trace isn't blank.
    """
    by_chapter: dict[str, list[FileRecord]] = {}
    for r in records:
        if r.chapter:
            by_chapter.setdefault(r.chapter, []).append(r)

    out: list[ChapterOutcome] = []
    for seed in needed:
        recs = by_chapter.get(seed.name)
        if recs:
            out.append(
                ChapterOutcome(
                    name=seed.name,
                    status="downloaded",
                    pages=_pages(recs),
                    title=_first([r.title for r in recs]),
                    date=_first([r.date for r in recs], seed.date),
                    error=None,
                )
            )
        elif seed.name in chapter_errors:
            out.append(
                ChapterOutcome(seed.name, "failed", 0, "", seed.date, chapter_errors[seed.name])
            )
        elif exit_code == 0:
            out.append(ChapterOutcome(seed.name, "skipped", 0, "", seed.date, None))
        else:
            out.append(ChapterOutcome(seed.name, "failed", 0, "", seed.date, None))

    needed_names = {s.name for s in needed}
    for chapter, recs in by_chapter.items():
        if chapter in needed_names:
            continue
        out.append(
            ChapterOutcome(
                name=chapter,
                status="downloaded",
                pages=_pages(recs),
                title=_first([r.title for r in recs]),
                date=_first([r.date for r in recs]),
                error=None,
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/downloads/test_outcomes.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/backend/downloads/outcomes.py backend/tests/downloads/test_outcomes.py
git commit -m "feat(downloads): reconcile per-chapter outcomes"
```

---

## Task 4: Thread-scoped per-chapter error collector

**Files:**
- Create: `backend/src/backend/downloads/capture.py`
- Test: `backend/tests/downloads/test_capture.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/downloads/test_capture.py`:

```python
import logging
import threading

from backend.downloads.capture import ChapterErrorCollector


def _record(msg: str, level: int = logging.ERROR) -> logging.LogRecord:
    rec = logging.LogRecord("gallery-dl.test", level, __file__, 1, msg, None, None)
    rec.thread = threading.get_ident()
    return rec


def test_buckets_error_to_current_chapter() -> None:
    ctx = ["5"]
    collector = ChapterErrorCollector(ctx, threading.get_ident())
    collector.emit(_record("boom 403"))
    assert collector.errors == {"5": "boom 403"}


def test_keeps_first_error_per_chapter() -> None:
    ctx = ["5"]
    collector = ChapterErrorCollector(ctx, threading.get_ident())
    collector.emit(_record("first"))
    collector.emit(_record("second"))
    assert collector.errors["5"] == "first"


def test_ignores_records_with_no_current_chapter() -> None:
    ctx = [""]
    collector = ChapterErrorCollector(ctx, threading.get_ident())
    collector.emit(_record("orphan"))
    assert collector.errors == {}


def test_ignores_records_from_other_threads() -> None:
    ctx = ["5"]
    collector = ChapterErrorCollector(ctx, thread_id=-1)
    collector.emit(_record("from-this-thread"))
    assert collector.errors == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_capture.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.downloads.capture`.

- [ ] **Step 3: Implement `capture.py`**

Create `backend/src/backend/downloads/capture.py`:

```python
"""Per-chapter failure-reason capture for gallery-dl runs.

A `ChapterErrorCollector` is a logging.Handler attached to the root logger
around `job.run()`. gallery-dl extractor loggers (e.g. `mangadex`) propagate to
root. The collector only banks WARNING+ records emitted on the worker thread
(filtered by `record.thread`) while a chapter context is set, so it never picks
up the event loop's own logging. The download worker is strictly serial, so a
process-global handler only ever serves one job at a time.
"""

from __future__ import annotations

import logging


class ChapterErrorCollector(logging.Handler):
    def __init__(self, chapter_ctx: list[str], thread_id: int) -> None:
        super().__init__(level=logging.WARNING)
        self._ctx = chapter_ctx
        self._thread_id = thread_id
        self.errors: dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self._thread_id:
            return
        chapter = self._ctx[0] if self._ctx else ""
        if not chapter:
            return
        # Keep the first (usually root-cause) error per chapter.
        self.errors.setdefault(chapter, record.getMessage())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/downloads/test_capture.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/backend/downloads/capture.py backend/tests/downloads/test_capture.py
git commit -m "feat(downloads): thread-scoped per-chapter error collector"
```

---

## Task 5: Wire the collector + chapter context into the gallery job

**Files:**
- Modify: `backend/src/backend/downloads/gallery.py` (`_ProgressDownloadJob` ~75-133, `run_download` ~290-313)
- Modify: `backend/tests/fakes.py` (`FakeGalleryConfig`, `FakeGallery.run_download`)
- Test: `backend/tests/downloads/test_gallery.py`

- [ ] **Step 1: Find all `run_download` callers (signature changes to 3-tuple)**

Run: `cd backend && rg -n "run_download" src tests`
Expected: callers are `worker.py` (`_execute_download`, updated in Task 7), `tests/fakes.py` (this task), and possibly `tests/downloads/test_gallery.py`. Note each — every unpacking of the return value must become a 3-tuple.

- [ ] **Step 2: Write the failing test (FakeGallery returns chapter_errors)**

Add to `backend/tests/downloads/test_gallery.py`:

```python
def test_fake_gallery_run_download_returns_chapter_errors() -> None:
    from pathlib import Path

    from backend.config import Settings
    from tests.fakes import FakeGallery, FakeGalleryConfig

    config = FakeGalleryConfig()
    config.manifest_for["https://example/x"] = ["ch1/001.jpg"]
    config.chapter_errors_for["https://example/x"] = {"1": "boom"}
    settings = Settings(data_dir=Path("/tmp/does-not-matter"))
    config.write_files = False
    gallery = FakeGallery(settings, config=config)

    result = gallery.run_download("https://example/x")
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert result[2] == {"1": "boom"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_gallery.py::test_fake_gallery_run_download_returns_chapter_errors -v`
Expected: FAIL — `AttributeError: chapter_errors_for` / return tuple has length 2.

- [ ] **Step 4: Update FakeGallery**

In `backend/tests/fakes.py`, add to `FakeGalleryConfig.__init__`:

```python
        # Optional per-URL captured per-chapter errors (chapter name -> reason),
        # surfaced by run_download to exercise outcome reconciliation.
        self.chapter_errors_for: dict[str, dict[str, str]] = {}
```

Change `FakeGallery.run_download`'s signature return annotation to
`tuple[int, list[FileRecord], dict[str, str]]` and its final `return` to:

```python
        return 0, emitted_records, dict(self._config.chapter_errors_for.get(url, {}))
```

- [ ] **Step 5: Update the real `_ProgressDownloadJob` to track the current chapter**

In `gallery.py`, import `threading` at the top and the collector:

```python
import logging
import os
import threading
```
```python
from backend.downloads.capture import ChapterErrorCollector
```

Add `_chapter_ctx` to the shared-state class attrs and inheritance. Change the class attribute block and `__init__`:

```python
    _on_file_complete: Callable[[str], None]
    _downloads_base: str
    _records: list[FileRecord]
    _skip_chapter: SkipChapterFn | None
    _chapter_ctx: list[str]
```

In `__init__`, add `"_chapter_ctx"` to the `_inherit_shared_state` attr list, and in the `else` (fresh-init) branch add:

```python
            self._chapter_ctx = [""]
```

So the inherited list becomes:

```python
        if not _inherit_shared_state(
            self,
            parent,
            "_on_file_complete",
            "_downloads_base",
            "_records",
            "_skip_chapter",
            "_chapter_ctx",
        ):
            assert on_file_complete is not None and downloads_base is not None
            self._on_file_complete = on_file_complete
            self._downloads_base = downloads_base
            self._records = []
            self._skip_chapter = skip_chapter
            self._chapter_ctx = [""]
```

Add a `handle_directory` override and set the chapter context at the start of `handle_url` (so errors logged during a page download attribute to the right chapter). Insert this method above `handle_url`:

```python
    def handle_directory(self, kwdict: dict[str, Any]) -> None:
        chapter = chapter_with_minor(kwdict)
        if chapter:
            self._chapter_ctx[0] = chapter
        super().handle_directory(kwdict)
```

And at the very top of `handle_url`, before the skip check, add:

```python
        chapter_ctx = chapter_with_minor(kwdict)
        if chapter_ctx:
            self._chapter_ctx[0] = chapter_ctx
```

(`chapter_with_minor` is already imported from `backend.downloads.postprocess`.)

- [ ] **Step 6: Attach the collector in `run_download` and return chapter_errors**

Replace the body of `run_download` after the `on_file_complete is None` guard with:

```python
        base = str(self._downloads_dir).rstrip(os.sep) + os.sep
        job = _ProgressDownloadJob(
            url,
            on_file_complete=on_file_complete,
            downloads_base=base,
            skip_chapter=skip_chapter,
        )
        collector = ChapterErrorCollector(job._chapter_ctx, threading.get_ident())
        root = logging.getLogger()
        root.addHandler(collector)
        try:
            exit_code = job.run()
        finally:
            root.removeHandler(collector)
        return exit_code, job._records, dict(collector.errors)
```

Also update the `on_file_complete is None` early return to a 3-tuple:

```python
        if on_file_complete is None:
            return DownloadJob(url).run(), [], {}
```

And update the return type annotation:

```python
    def run_download(
        self,
        url: str,
        on_file_complete: Callable[[str], None] | None = None,
        skip_chapter: SkipChapterFn | None = None,
    ) -> tuple[int, list[FileRecord], dict[str, str]]:
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/downloads/test_gallery.py -v`
Expected: PASS. If `test_gallery.py` had existing tests unpacking a 2-tuple from `run_download`, update them to `code, records, errors = ...` (or `*_,` ) per the Step 1 grep.

- [ ] **Step 8: Commit**

```bash
git add backend/src/backend/downloads/gallery.py backend/tests/fakes.py backend/tests/downloads/test_gallery.py
git commit -m "feat(downloads): capture per-chapter errors during gallery-dl run"
```

---

## Task 6: Service persistence (manifest dates/discovered, outcomes, reset)

**Files:**
- Modify: `backend/src/backend/downloads/service.py` (`save_manifest` ~89-109, `reset_to_pending` ~170-190; add `save_chapter_outcomes`, `get_chapter_outcomes`)
- Test: `backend/tests/downloads/test_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/downloads/test_service.py`:

```python
async def test_save_manifest_records_discovered_and_dates(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(
        db, d.id, ["1", "2"], dates={"1": "2026-01-01"}, discovered=5
    )
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.chapters_total == 2  # needed
    assert fetched.chapters_discovered == 5
    outcomes = await service.get_chapter_outcomes(db, d.id)
    assert [o.name for o in outcomes] == ["1", "2"]
    assert outcomes[0].status == "pending"
    assert outcomes[0].date == "2026-01-01"


async def test_save_chapter_outcomes_updates_rows_and_counts(db: aiosqlite.Connection) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1", "2"], discovered=2)
    await service.save_chapter_outcomes(
        db,
        d.id,
        [
            ChapterOutcome("1", "downloaded", 12, "Intro", "2026-01-01", None),
            ChapterOutcome("2", "failed", 0, "", "", "403 Forbidden"),
        ],
    )
    rows = await service.get_chapter_outcomes(db, d.id)
    by_name = {r.name: r for r in rows}
    assert by_name["1"].status == "downloaded"
    assert by_name["1"].pages == 12
    assert by_name["1"].title == "Intro"
    assert by_name["2"].status == "failed"
    assert by_name["2"].error == "403 Forbidden"
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.chapters_failed == 1


async def test_save_chapter_outcomes_inserts_synthesized_chapter(db: aiosqlite.Connection) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, [], discovered=0)
    await service.save_chapter_outcomes(
        db, d.id, [ChapterOutcome("9", "downloaded", 3, "", "", None)]
    )
    rows = await service.get_chapter_outcomes(db, d.id)
    assert [r.name for r in rows] == ["9"]


async def test_reset_to_pending_clears_new_count_columns(db: aiosqlite.Connection) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1"], discovered=3)
    await service.save_chapter_outcomes(
        db, d.id, [ChapterOutcome("1", "failed", 0, "", "", "boom")]
    )
    await service.finish_job(db, d.id, exit_code=1, files_downloaded=0)
    assert await service.reset_to_pending(db, d.id) is True
    fetched = await service.get(db, d.id)
    assert fetched is not None
    assert fetched.chapters_discovered is None
    assert fetched.chapters_failed is None
    assert await service.get_chapter_outcomes(db, d.id) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/downloads/test_service.py -k "discovered or chapter_outcomes or new_count_columns" -v`
Expected: FAIL — `save_manifest()` got unexpected kwarg `dates`; `get_chapter_outcomes` missing.

- [ ] **Step 3: Extend `save_manifest`**

In `service.py`, add the `outcomes` import at the top:

```python
from backend.downloads.outcomes import ChapterOutcome
```

Replace `save_manifest` with:

```python
async def save_manifest(
    db: aiosqlite.Connection,
    download_id: int,
    chapter_names: list[str],
    *,
    dates: dict[str, str] | None = None,
    discovered: int | None = None,
) -> None:
    """Persist the chapter list discovered by the metadata pull.

    Each needed chapter gets one row in `download_files` (status 'pending', with
    its discovered date when known). `files_expected` and `chapters_total` carry
    the needed count; `chapters_discovered` carries the total seen before
    skip-filtering (defaults to the needed count when not supplied).
    """
    dates = dates or {}
    await db.execute("DELETE FROM download_files WHERE download_id = ?", (download_id,))
    await db.executemany(
        "INSERT INTO download_files(download_id, idx, relpath, status, date) "
        "VALUES(?, ?, ?, 'pending', ?)",
        [(download_id, i, name, dates.get(name, "")) for i, name in enumerate(chapter_names)],
    )
    n = len(chapter_names)
    disc = discovered if discovered is not None else n
    await db.execute(
        "UPDATE downloads SET files_expected = ?, chapters_total = ?, "
        "chapters_discovered = ? WHERE id = ?",
        (n, n, disc, download_id),
    )
    await db.commit()
```

- [ ] **Step 4: Add `save_chapter_outcomes` and `get_chapter_outcomes`**

Add after `save_manifest`/`get_manifest` in `service.py`:

```python
async def save_chapter_outcomes(
    db: aiosqlite.Connection,
    download_id: int,
    outcomes: list[ChapterOutcome],
) -> None:
    """Persist per-chapter outcomes onto the manifest rows (matching by chapter
    name); append rows for chapters that downloaded but weren't in the manifest.
    Also denormalises the failed count onto the download row.
    """
    async with db.execute(
        "SELECT relpath, idx FROM download_files WHERE download_id = ?",
        (download_id,),
    ) as cur:
        rows = await cur.fetchall()
    idx_by_name = {r["relpath"]: r["idx"] for r in rows}
    next_idx = (max(idx_by_name.values()) + 1) if idx_by_name else 0
    for o in outcomes:
        if o.name in idx_by_name:
            await db.execute(
                "UPDATE download_files SET status = ?, pages = ?, title = ?, "
                "date = COALESCE(NULLIF(?, ''), date), error = ? "
                "WHERE download_id = ? AND relpath = ?",
                (o.status, o.pages, o.title, o.date, o.error, download_id, o.name),
            )
        else:
            await db.execute(
                "INSERT INTO download_files"
                "(download_id, idx, relpath, status, pages, title, date, error) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (download_id, next_idx, o.name, o.status, o.pages, o.title, o.date, o.error),
            )
            next_idx += 1
    failed = sum(1 for o in outcomes if o.status == "failed")
    await db.execute(
        "UPDATE downloads SET chapters_failed = ? WHERE id = ?",
        (failed, download_id),
    )
    await db.commit()


async def get_chapter_outcomes(
    db: aiosqlite.Connection, download_id: int
) -> list[ChapterOutcome]:
    """Return persisted per-chapter outcomes ordered by manifest index.

    Rows written before this feature (status NULL) surface as status 'pending'.
    """
    async with db.execute(
        "SELECT relpath, status, pages, title, date, error "
        "FROM download_files WHERE download_id = ? ORDER BY idx ASC",
        (download_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [
        ChapterOutcome(
            name=r["relpath"],
            status=r["status"] or "pending",  # type: ignore[arg-type]
            pages=r["pages"] or 0,
            title=r["title"] or "",
            date=r["date"] or "",
            error=r["error"],
        )
        for r in rows
    ]
```

Note: `ChapterOutcome.status` is typed `Literal[...]`; the `r["status"] or "pending"` returns a plain `str`. Add `# type: ignore[arg-type]` as shown (legacy rows are the only non-literal path and the frontend tolerates the string).

- [ ] **Step 5: Clear new columns on requeue**

In `reset_to_pending`, extend the UPDATE's SET clause to also null the new columns. Change the SET list to include:

```python
        "UPDATE downloads SET status = 'pending', started_at = NULL, "
        "finished_at = NULL, exit_code = NULL, files_downloaded = 0, "
        "files_expected = NULL, chapters_total = NULL, "
        "chapters_discovered = NULL, chapters_failed = NULL, error = NULL, "
        "postprocess_status = NULL, postprocess_chapters_packed = NULL, "
        "postprocess_error = NULL "
        "WHERE id = ? AND status IN ('completed', 'failed', 'cancelled')",
```

(The existing `DELETE FROM download_files` already clears per-chapter rows.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/downloads/test_service.py -v`
Expected: PASS (existing + 4 new tests). The existing `test_reset_to_pending_clears_terminal_fields_and_manifest` still passes.

- [ ] **Step 7: Commit**

```bash
git add backend/src/backend/downloads/service.py backend/tests/downloads/test_service.py
git commit -m "feat(downloads): persist per-chapter outcomes + discovered count"
```

---

## Task 7: Worker — thread metadata, reconcile, persist outcomes

**Files:**
- Modify: `backend/src/backend/downloads/worker.py` (`_process` ~128-167, `_extract_metadata` ~198-218, `_execute_download` ~220-253)
- Test: `backend/tests/downloads/test_worker.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/downloads/test_worker.py`:

```python
async def test_worker_persists_per_chapter_outcomes(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    # Two chapters discovered; chapter 2 fails (no records + captured error).
    config.chapter_dates_for["https://example/x"] = {
        ("S", "1"): "2026-01-01",
        ("S", "2"): "2026-01-02",
    }
    config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg", "fake/S/c1/002.jpg"]
    config.records_for["https://example/x"] = _make_records_for_chapter(
        settings.downloads_dir, "S", "1"
    )
    config.chapter_errors_for["https://example/x"] = {"2": "403 Forbidden"}
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()

        async def done() -> bool:
            row = await downloads_service.get(db, d.id)
            return row is not None and row.status == "completed"

        await _wait_for(done)

        row = await downloads_service.get(db, d.id)
        assert row is not None
        assert row.chapters_discovered == 2
        assert row.chapters_total == 2  # needed
        assert row.chapters_failed == 1
        outcomes = await downloads_service.get_chapter_outcomes(db, d.id)
        by_name = {o.name: o for o in outcomes}
        assert by_name["1"].status == "downloaded"
        assert by_name["1"].pages == 2
        assert by_name["2"].status == "failed"
        assert by_name["2"].error == "403 Forbidden"
    finally:
        await worker.stop()
```

Note: the FakeGallery's chapter key for records is the record's `chapter` field (`"1"`), matching the manifest name derived from `chapter_dates_for`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_worker.py::test_worker_persists_per_chapter_outcomes -v`
Expected: FAIL — `chapters_discovered`/`get_chapter_outcomes` not populated (worker doesn't persist them yet).

- [ ] **Step 3: Update imports + `_extract_metadata` return**

In `worker.py`, add imports:

```python
from backend.downloads.outcomes import ChapterSeed, reconcile_outcomes
```

Change `_extract_metadata` to return `(needed_seeds, discovered)`:

```python
    async def _extract_metadata(
        self, job: Download, skip_chapter: SkipChapterFn | None
    ) -> tuple[list[ChapterSeed], int]:
        """Metadata-only pull: discover the chapter list (+ release dates) and
        seed the target's series_name / status / tags. Returns the needed
        chapters (after skip-filtering) with their dates, plus the total
        discovered count.
        """
        meta = await asyncio.to_thread(self._gallery.extract_metadata, job.url)
        if job.target_id is not None and meta.series_name:
            await targets_service.set_name(self._db, job.target_id, meta.series_name)
            self._publish(downloads_event("target_named", id=job.target_id, name=meta.series_name))
        if job.target_id is not None and meta.series_status:
            await targets_service.set_series_status(self._db, job.target_id, meta.series_status)
        if job.target_id is not None and meta.series_tags:
            await targets_service.set_series_tags(self._db, job.target_id, meta.series_tags)
        needed: list[ChapterSeed] = []
        for (manga, chapter), date in meta.chapter_dates.items():
            if skip_chapter is not None and manga and chapter and skip_chapter(manga, chapter):
                continue
            needed.append(ChapterSeed(name=chapter, date=date))
        return needed, len(meta.chapter_dates)
```

- [ ] **Step 4: Update `_process` to thread the seeds through**

In `_process`, replace the metadata + manifest block. Change the local `chapter_names: list[str] = []` declaration to `needed: list[ChapterSeed] = []`, and update the try body:

```python
        needed: list[ChapterSeed] = []
        records: list[FileRecord] = []
        exit_code = 1
        cancelled = False
        chapters_seen: set[str] = set()
        try:
            skip_chapter = await self._build_skip_chapter(job)
            needed, discovered = await self._extract_metadata(job, skip_chapter)
            if self._cancel_flags.get(job.id, False):
                await service.mark_cancelled(self._db, job.id, 0)
                self._publish(downloads_event("updated", id=job.id, status="cancelled"))
                return
            await service.save_manifest(
                self._db,
                job.id,
                [s.name for s in needed],
                dates={s.name: s.date for s in needed if s.date},
                discovered=discovered,
            )
            self._publish(downloads_event("manifest_ready", id=job.id, files=len(needed)))
            try:
                exit_code, records, cancelled = await self._execute_download(
                    job, skip_chapter, chapters_seen, needed
                )
            finally:
                self._live.clear(job.id)
        except Exception as exc:
            await self._handle_failure(job, exc, len(chapters_seen))
            return
```

- [ ] **Step 5: Update `_execute_download` to reconcile + persist outcomes**

Replace `_execute_download` with (note the new `needed` parameter and the 3-tuple unpack from `run_download`):

```python
    async def _execute_download(
        self,
        job: Download,
        skip_chapter: SkipChapterFn | None,
        chapters_seen: set[str],
        needed: list[ChapterSeed],
    ) -> tuple[int, list[FileRecord], bool]:
        """Run the real download; reconcile + persist per-chapter outcomes;
        return (exit_code, file records, was_cancelled)."""
        await service.mark_running(self._db, job.id)
        self._publish(downloads_event("updated", id=job.id, status="running"))
        self._live.start(job.id)
        exit_code, records, chapter_errors = await asyncio.to_thread(
            self._gallery.run_download,
            job.url,
            self._make_progress_cb(job.id, chapters_seen),
            skip_chapter,
        )
        cancelled = self._cancel_flags.get(job.id, False)
        outcomes = reconcile_outcomes(needed, records, chapter_errors, exit_code)
        await service.save_chapter_outcomes(self._db, job.id, outcomes)
        present = sum(1 for o in outcomes if o.status == "downloaded")
        if not present:
            # Fall back to the live/record-derived count when reconciliation
            # produced no downloaded rows (e.g. extractors with empty chapter
            # metadata and no records keyed by chapter).
            present = max(len(chapters_seen), count_present_chapters([r.path for r in records]))
        if cancelled:
            await service.mark_cancelled(self._db, job.id, present)
            self._publish(downloads_event("updated", id=job.id, status="cancelled"))
        else:
            await service.finish_job(self._db, job.id, exit_code, present)
            terminal = "completed" if exit_code == 0 else "failed"
            self._publish(downloads_event("updated", id=job.id, status=terminal))
        return exit_code, records, cancelled
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/downloads/test_worker.py -v`
Expected: PASS — the new test plus all existing worker tests (they assert `files_downloaded`/`chapters_total`, which still hold).

- [ ] **Step 7: Commit**

```bash
git add backend/src/backend/downloads/worker.py backend/tests/downloads/test_worker.py
git commit -m "feat(downloads): worker persists discovered count + per-chapter outcomes"
```

---

## Task 8: Progress endpoint returns persisted truth for terminal jobs

**Files:**
- Modify: `backend/src/backend/downloads/router.py` (`get_progress` ~146-178)
- Test: `backend/tests/downloads/test_router.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/downloads/test_router.py` (uses the `client`/`gallery` fixtures from `tests/conftest.py`). Inspect the top of the existing file first (`rg -n "def test" tests/downloads/test_router.py | head`) to match its style; then add:

```python
def test_progress_reports_persisted_outcomes_for_terminal_job(client, gallery) -> None:
    gallery.config.chapter_dates_for["https://example/x"] = {
        ("S", "1"): "2026-01-01",
        ("S", "2"): "2026-01-02",
    }
    gallery.config.manifest_for["https://example/x"] = ["fake/S/c1/001.jpg"]
    gallery.config.chapter_errors_for["https://example/x"] = {"2": "boom"}

    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    job_id = created["id"]

    # Poll the detail endpoint until terminal.
    import time

    deadline = time.time() + 5
    while time.time() < deadline:
        row = client.get(f"/api/downloads/{job_id}").json()
        if row["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.02)

    prog = client.get(f"/api/downloads/{job_id}/progress").json()
    assert prog["chapters_discovered"] == 2
    assert prog["chapters_failed"] == 1
    names = {c["name"]: c for c in prog["chapters"]}
    assert names["1"]["status"] == "downloaded"
    assert names["2"]["status"] == "failed"
    assert names["2"]["error"] == "boom"
```

If `manifest_for` for chapter "1" needs a matching `FileRecord` to count as downloaded, also set `gallery.config.records_for["https://example/x"]` with a record whose `chapter="1"` (mirror `_make_records_for_chapter` from `test_worker.py`). Verify against how `FakeGallery` maps manifest entries to chapters.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_router.py::test_progress_reports_persisted_outcomes_for_terminal_job -v`
Expected: FAIL — `chapters_discovered` missing from `ProgressOut`; chapter `status`/`error` absent.

- [ ] **Step 3: Rewrite `get_progress`**

In `router.py`, add imports:

```python
from backend.downloads.constants import TERMINAL_STATUSES
from backend.downloads.outcomes import ChapterOutcome
```
(`TERMINAL_STATUSES` is already imported in this file — confirm and don't duplicate.)

Replace `get_progress` with:

```python
@router.get("/downloads/{download_id}/progress", operation_id="getDownloadProgress")
async def get_progress(
    download: DownloadDep,
    db: DbDep,
    settings: SettingsDep,
    live: LiveProgressDep,
) -> ProgressOut:
    manifest = await service.get_manifest(db, download.id)

    if download.status in TERMINAL_STATUSES:
        outcomes = await service.get_chapter_outcomes(db, download.id)
        if any(o.status != "pending" for o in outcomes):
            return _progress_from_outcomes(download, outcomes)
        # Legacy terminal job (no persisted outcomes): keep neutral fallback.
        chapters = chapter_progress(
            manifest, settings.downloads_dir, download.status, download.postprocess_status
        )
        return _legacy_progress(download, chapters)

    completed = live.snapshot(download.id)
    if completed is not None:
        chapters = chapter_progress_from_completed(
            manifest, completed, download.status, download.postprocess_status
        )
    else:
        chapters = chapter_progress(
            manifest, settings.downloads_dir, download.status, download.postprocess_status
        )
    return _legacy_progress(download, chapters)


def _legacy_progress(download: Download, chapters: list) -> ProgressOut:
    files_present = sum(c.files_present for c in chapters)
    return ProgressOut(
        status=download.status,
        files_expected=download.files_expected,
        files_present=files_present,
        chapters_discovered=download.chapters_discovered,
        chapters_needed=download.chapters_total,
        chapters=[
            ChapterProgress(
                name=c.name,
                files_total=c.files_total,
                files_present=c.files_present,
                stage=c.stage,
            )
            for c in chapters
        ],
    )


_OUTCOME_STAGE = {
    "downloaded": "downloaded",
    "skipped": "completed",
    "failed": "downloading",
    "pending": "downloading",
}


def _progress_from_outcomes(download: Download, outcomes: list[ChapterOutcome]) -> ProgressOut:
    downloaded = sum(1 for o in outcomes if o.status == "downloaded")
    failed = sum(1 for o in outcomes if o.status == "failed")
    skipped = sum(1 for o in outcomes if o.status == "skipped")
    return ProgressOut(
        status=download.status,
        files_expected=download.files_expected,
        files_present=downloaded,
        chapters_discovered=download.chapters_discovered,
        chapters_needed=download.chapters_total,
        chapters_downloaded=downloaded,
        chapters_failed=failed,
        chapters_skipped=skipped,
        chapters=[
            ChapterProgress(
                name=o.name,
                files_total=max(o.pages, 1),
                files_present=o.pages if o.status == "downloaded" else 0,
                stage=_OUTCOME_STAGE.get(o.status, "downloading"),
                status=o.status,
                pages=o.pages,
                title=o.title or None,
                date=o.date or None,
                error=o.error,
            )
            for o in outcomes
        ],
    )
```

(`Download` is already imported in `router.py`; keep the existing `chapter_progress` / `chapter_progress_from_completed` imports.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/downloads/test_router.py -v`
Expected: PASS (existing router tests + the new one).

- [ ] **Step 5: Backend full check**

Run: `mise run lint:backend && mise run typecheck:backend && mise run test:backend`
Expected: all green. Fix any ruff/ty findings (`mise run fix:backend` for formatting).

- [ ] **Step 6: Commit**

```bash
git add backend/src/backend/downloads/router.py backend/tests/downloads/test_router.py
git commit -m "feat(downloads): progress endpoint returns persisted per-chapter truth"
```

---

## Task 9: Regenerate the typed frontend client

**Files:**
- Modify (generated): `frontend/src/api/types.gen.ts`, `frontend/src/api/@tanstack/react-query.gen.ts`, and sibling generated files.

- [ ] **Step 1: Boot the backend so OpenAPI is live**

The codegen reads `http://localhost:8000/openapi.json` (`frontend/openapi-ts.config.ts`). Start the dev server in the background:

Run: `cd backend && uv run uvicorn backend.main:app --port 8000 &`
Then wait for it: `until curl -sf http://localhost:8000/openapi.json >/dev/null; do sleep 0.3; done && echo READY`
Expected: `READY`.

- [ ] **Step 2: Regenerate**

Run: `mise run generate:client`
Expected: writes regenerated files under `frontend/src/api/`.

- [ ] **Step 3: Stop the background backend**

Run: `kill %1 2>/dev/null || pkill -f "uvicorn backend.main:app"`

- [ ] **Step 4: Verify the new fields landed**

Run: `cd frontend && rg -n "chapters_discovered|chapters_failed" src/api/types.gen.ts`
Expected: matches in the `Download` and `ProgressOut` types; `ChapterProgress` shows `status`, `pages`, `title`, `date`, `error`.

- [ ] **Step 5: Typecheck + commit**

Run: `mise run typecheck:frontend`
Expected: PASS.

```bash
git add frontend/src/api
git commit -m "chore(api): regenerate client for verbose trace fields"
```

---

## Task 10: Frontend status helpers for chapter outcomes

**Files:**
- Modify: `frontend/src/lib/status.ts` (`STATUS_TONES` ~32-43, `CHAPTER_STAGE_LABELS` ~105-114)
- Test: `frontend/src/lib/status.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/lib/status.test.ts` (import `chapterStageLabel`, `statusTone` are already imported in the file — add `chapterStageLabel` if missing):

```python
# (TypeScript — add inside the file)
```
```ts
describe("chapter outcome presentation", () => {
  it("labels downloaded/skipped/failed chapter outcomes", () => {
    expect(chapterStageLabel("downloaded")).toBe("Downloaded");
    expect(chapterStageLabel("skipped")).toBe("Skipped");
    expect(chapterStageLabel("failed")).toBe("Failed");
  });

  it("tones failed as error and skipped as muted", () => {
    expect(statusTone("failed")).toBe("error");
    expect(statusTone("skipped")).toBe("muted");
    expect(statusTone("downloaded")).toBe("info");
  });
});
```

Ensure `statusTone` and `chapterStageLabel` are in the test file's import list at the top.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/lib/status.test.ts`
Expected: FAIL — `chapterStageLabel("skipped")` returns `"skipped"`, `statusTone("skipped")` returns `"muted"` already (that one may pass) but `chapterStageLabel("skipped")` / `chapterStageLabel("failed")` fail.

- [ ] **Step 3: Extend the maps**

In `status.ts`, add to `STATUS_TONES` (alongside the existing entries):

```ts
  skipped: "muted",
```

(`failed: "error"` and `downloaded: "info"` already exist.)

Add to `CHAPTER_STAGE_LABELS`:

```ts
  downloaded: "Downloaded",
  skipped: "Skipped",
  failed: "Failed",
  pending: "Pending",
```

(Keep the existing `downloading`/`processing`/`completed` entries; `downloaded` already exists — don't duplicate it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/lib/status.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/status.ts frontend/src/lib/status.test.ts
git commit -m "feat(ui): status tones + labels for chapter outcomes"
```

---

## Task 11: ProgressCard — summary line + per-chapter outcome badges

**Files:**
- Modify: `frontend/src/components/ProgressCard.tsx`
- Test: `frontend/src/components/ProgressCard.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ProgressCard.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { ProgressCard } from "./ProgressCard";

afterEach(() => {
  mockFetch(undefined);
});

const PROGRESS = {
  status: "completed",
  files_expected: 2,
  files_present: 1,
  chapters_discovered: 3,
  chapters_needed: 2,
  chapters_downloaded: 1,
  chapters_failed: 1,
  chapters_skipped: 0,
  chapters: [
    {
      name: "1",
      files_total: 12,
      files_present: 12,
      stage: "downloaded",
      status: "downloaded",
      pages: 12,
      title: "Intro",
      date: "2026-01-01",
      error: null,
    },
    {
      name: "2",
      files_total: 1,
      files_present: 0,
      stage: "downloading",
      status: "failed",
      pages: 0,
      title: null,
      date: null,
      error: "403 Forbidden",
    },
  ],
};

describe("ProgressCard (terminal job)", () => {
  it("shows the discovered/needed/downloaded/failed summary and outcome badges", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress")) return jsonResponse(PROGRESS);
      return jsonResponse({});
    });

    renderWithProviders(<ProgressCard jobId={1} status="completed" startedAt={null} />);

    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    // Per-chapter badges from outcome status.
    expect(screen.getByText("Downloaded")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    // Summary counts present somewhere in the card.
    expect(screen.getByText(/discovered 3/i)).toBeInTheDocument();
    expect(screen.getByText(/failed 1/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/components/ProgressCard.test.tsx`
Expected: FAIL — no "Failed" badge / no summary text rendered.

- [ ] **Step 3: Update `ProgressCard.tsx`**

Update the `chapterStage` helper and the badge/summary rendering. Replace the `chapterStage` function with an outcome-aware label/tone selection that prefers `ch.status` when present:

```tsx
import { chapterStageLabel, isTerminal, type Status, statusTone } from "../lib/status";
```

Replace the `type ChapterStage` + `chapterStage` block with:

```tsx
function chapterBadge(ch: ChapterProgress): { label: string; tone: ReturnType<typeof statusTone> } {
  // Terminal outcomes carry an explicit `status`; live rows only carry `stage`.
  const key = ch.status ?? ch.stage;
  return { label: chapterStageLabel(key), tone: statusTone(key) };
}
```

Add a summary line above the chapter list (inside the returned `<Stack>`, after the `<Progress>` bar). Insert:

```tsx
      {(data.chapters_discovered != null || data.chapters_failed > 0) && (
        <Text size="xs" c="dimmed" ff="monospace">
          {[
            data.chapters_discovered != null ? `discovered ${data.chapters_discovered}` : null,
            data.chapters_needed != null ? `needed ${data.chapters_needed}` : null,
            `downloaded ${data.chapters_downloaded}`,
            data.chapters_skipped > 0 ? `skipped ${data.chapters_skipped}` : null,
            `failed ${data.chapters_failed}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </Text>
      )}
```

In the per-chapter row, replace the `<Pill>` usage and add pages/date + error tooltip. Replace the row body's name + pill section with:

```tsx
                const badge = chapterBadge(ch);
                const label = ch.name || "(root)";
                const meta = [
                  ch.pages ? `${ch.pages}p` : null,
                  ch.date || null,
                ]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <Group
                    key={label}
                    justify="space-between"
                    gap="xs"
                    wrap="nowrap"
                    py={6}
                    px="xs"
                    style={{
                      borderTop: i > 0 ? "1px solid var(--app-border-subtle)" : undefined,
                    }}
                  >
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text
                        size="sm"
                        ff="monospace"
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={ch.title || label}
                      >
                        {label}
                      </Text>
                      {meta && (
                        <Text size="xs" c="dimmed" ff="monospace">
                          {meta}
                        </Text>
                      )}
                    </Stack>
                    <Tooltip
                      label={ch.error ?? ""}
                      disabled={!ch.error}
                      withArrow
                      multiline
                      w={260}
                    >
                      <Pill tone={badge.tone}>{badge.label}</Pill>
                    </Tooltip>
                  </Group>
                );
```

Add `Tooltip` to the `@mantine/core` import at the top of the file, and remove the now-unused `chapterStageLabel`-only path if the old `ChapterStage` type/`chapterStage` function is no longer referenced.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/components/ProgressCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

Run: `cd frontend && pnpm typecheck`
Expected: PASS.

```bash
git add frontend/src/components/ProgressCard.tsx frontend/src/components/ProgressCard.test.tsx
git commit -m "feat(ui): ProgressCard shows per-chapter outcomes + summary"
```

---

## Task 12: RecentRow — show failed count in the list

**Files:**
- Modify: `frontend/src/components/RecentRow.tsx` (`chapterCountLabel` ~7-13)
- Test: `frontend/src/components/RecentRow.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/RecentRow.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Download } from "../api/types.gen";
import { renderWithProviders } from "../test/render";
import { RecentRow } from "./RecentRow";

function makeJob(overrides: Partial<Download>): Download {
  return {
    id: 1,
    url: "https://example/x",
    name: null,
    extractor: "fake",
    status: "completed",
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
    exit_code: 0,
    files_downloaded: 0,
    files_expected: null,
    chapters_total: 5,
    chapters_discovered: 5,
    chapters_failed: 0,
    error: null,
    postprocess_status: null,
    postprocess_chapters_packed: null,
    postprocess_error: null,
    output_dir: null,
    target_id: null,
    ...overrides,
  } as Download;
}

const noop = () => {};

describe("RecentRow chapter label", () => {
  it("appends the failed count when chapters failed", () => {
    renderWithProviders(
      <RecentRow
        item={makeJob({ chapters_total: 5, chapters_failed: 2 })}
        selected={false}
        cancelling={false}
        inflight={false}
        isCancelPending={false}
        isRequeuePending={false}
        onSelect={noop}
        onCancel={noop}
        onRequeue={noop}
      />,
    );
    expect(screen.getByText(/2 failed/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/components/RecentRow.test.tsx`
Expected: FAIL — no "2 failed" text.

- [ ] **Step 3: Update `chapterCountLabel`**

In `RecentRow.tsx`, replace `chapterCountLabel`:

```tsx
function chapterCountLabel(item: Download): string {
  const total = item.chapters_total;
  if (total == null) return "—";
  const packed = item.postprocess_chapters_packed;
  const base = packed != null ? `${packed}/${total} ch.` : `${total} ch.`;
  const failed = item.chapters_failed ?? 0;
  return failed > 0 ? `${base} · ${failed} failed` : base;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/components/RecentRow.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RecentRow.tsx frontend/src/components/RecentRow.test.tsx
git commit -m "feat(ui): RecentRow shows failed chapter count"
```

---

## Task 13: Final full check

- [ ] **Step 1: Run all CI checks**

Run: `mise run check`
Expected: lint + typecheck + test all green for backend and frontend. Apply `mise run fix` for any formatting nits and re-run.

- [ ] **Step 2: Manual smoke (optional but recommended)**

Run: `mise run dev`, submit a real manga URL, watch the Jobs tab show discovered/needed/downloaded counts live, let it finish, reload, and confirm the past job still shows per-chapter outcomes (downloaded/skipped/failed with reasons). Requeue and confirm counts reset.

- [ ] **Step 3: Commit any final fixups**

```bash
git add -A
git commit -m "chore: verbose job trace cleanup" || echo "nothing to commit"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Discovered/needed/downloaded counts → Tasks 1, 2, 6, 7, 8 (`chapters_discovered`, `chapters_total`, `files_downloaded`, ProgressOut counts).
- Per-chapter failures + reason → Tasks 3, 4, 5, 7 (collector + reconciliation + persistence).
- Per-chapter detail (pages/date/title) → Tasks 1, 3, 6, 7, 11.
- Past-job screen shows persisted truth → Task 8 (endpoint) + Task 11 (ProgressCard).
- Legacy rows handled → Task 8 (`_legacy_progress` fallback when status NULL).
- Requeue resets new columns → Task 6.

**Placeholder scan:** No TBDs; every code step shows full code; commands have expected output. (Two steps intentionally include a grep/inspection action — Task 5 Step 1, Task 8 Step 1 — to adapt to existing test details; these are explicit actions, not vague placeholders.)

**Type consistency:** `ChapterSeed`/`ChapterOutcome`/`reconcile_outcomes` (Task 3) are reused verbatim in Tasks 6/7/8. `run_download` 3-tuple introduced in Task 5 is consumed in Task 7. `save_manifest(..., dates=, discovered=)` (Task 6) is called with those exact kwargs in Task 7. Frontend `ChapterProgress.status`/`pages`/`date`/`error` (Task 2 → regenerated Task 9) are consumed in Task 11.
