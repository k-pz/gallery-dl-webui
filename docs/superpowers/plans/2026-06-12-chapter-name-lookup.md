# Chapter Name Lookup for Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every chapter row in a download's manifest carries a human-readable
chapter title from the moment the manifest is ready — including chapters that
end up skipped or failed — instead of titles existing only for chapters that
actually downloaded. When the original source doesn't expose titles, an
optional per-target *metadata source URL* (any gallery-dl-supported site, e.g.
the same series on MangaDex) provides them as a fill-only fallback.

**Architecture:** Two phases.

- **Phase A (tasks 1–7):** the existing metadata-only sim pass
  (`_MetadataSimulationJob`) already reads every chapter's kwdict to bank
  `(manga, chapter) → date`; extend it to also bank `title`. Thread the title
  through `ChapterSeed` → `save_manifest` (the `download_files.title` column
  already exists) → `reconcile_outcomes` (seed title as fallback for
  skipped/failed/pending rows) → the progress endpoint → `ProgressCard`.
  No API shape changes: `ChapterProgress.title` already exists; it just
  starts being populated for non-downloaded chapters.
- **Phase B (tasks 8–12):** a nullable `targets.metadata_source_url` column,
  editable via `PATCH /targets/{id}`. During `_extract_metadata`, when needed
  chapters still lack titles and the target has a metadata source URL, run a
  second `extract_metadata` against that URL and fill titles by chapter
  number (fill-only, best-effort — a failing secondary lookup never fails the
  download). This reuses the gallery-dl extractor machinery wholesale; no
  bespoke HTTP client.

**Tech Stack:** Backend — FastAPI, aiosqlite (SQLite), gallery-dl Python API,
pytest, ruff, ty. Frontend — React 19, Mantine, TanStack Query, hey-api
generated client, vitest, biome.

**Toolchain note:** All commands go through `mise`. Backend one-offs:
`cd backend && uv run <cmd>`. Frontend one-offs: `cd frontend && pnpm <cmd>`.
Never invoke `python`/`pytest`/`node` directly.

---

## Reference: shapes used across tasks

- `MetadataResult.chapter_titles: dict[tuple[str, str], str]` (new field,
  `backend/src/backend/downloads/gallery.py`) — `(manga, chapter) → title`,
  only entries with a non-empty title.
- `ChapterSeed` (`backend/src/backend/downloads/outcomes.py`) gains
  `title: str = ""`.
- `service.save_manifest(db, id, chapter_names, *, dates=None, titles=None,
  discovered=None)` (new `titles` kwarg).
- `save_chapter_outcomes` UPDATE changes `title = ?` to
  `title = COALESCE(NULLIF(?, ''), title)` (same pattern `date` already uses)
  so reconciliation never blanks a seeded title.
- `_filter_needed_chapters(chapter_dates, chapter_titles, skip_chapter)`
  (worker) — extra `chapter_titles` parameter.
- New `targets` column: `metadata_source_url TEXT` (nullable). Surfaced on
  `Target`, settable via `TargetUpdate` (empty string clears).
- `FakeGalleryConfig.chapter_titles_for: dict[str, dict[tuple[str, str], str]]`
  (`backend/tests/fakes.py`).

**Invariant to preserve:** in `_MetadataSimulationJob._capture`, the
"return True → skip child descent" criterion stays *exactly*
`manga and chapter and date`. Title absence must never force a per-chapter
page fetch — many extractors simply have no titles, and descending costs two
HTTP requests + a rate-limit sleep per chapter.

**Toolchain gotcha:** the pinned interpreter is Python 3.14 (see `mise.toml`),
where PEP 758 makes `except OSError, ValueError:` (no parentheses, no `as`)
valid syntax — `comic_metadata.py` uses it and ruff format *enforces* the
unparenthesized style. A system Python older than 3.14 will report it as a
SyntaxError; that is your interpreter being wrong, not the code. Always run
checks via `uv run` / `mise run` so the pinned toolchain is used.

---

## Task 1: Capture chapter titles in the metadata sim pass

**Files:**
- Modify: `backend/src/backend/downloads/gallery.py`
  (`MetadataResult` ~31-65, `_MetadataSimulationJob` ~158-259,
  `Gallery.extract_metadata` ~294-312)
- Modify: `backend/tests/fakes.py` (`FakeGalleryConfig`, `FakeGallery.extract_metadata`)
- Test: `backend/tests/downloads/test_gallery.py`

- [ ] **Step 1: Write the failing tests**

`test_gallery.py` already unit-tests `_MetadataSimulationJob._capture` via
fabricated kwdicts (check existing tests for the established pattern — if
capture is only exercised indirectly, test through a job instance constructed
the same way existing tests do). Add:

```python
def test_capture_banks_chapter_title_alongside_date(metadata_job) -> None:
    kwdict = {
        "manga": "S",
        "chapter": 12,
        "date": datetime(2026, 1, 5),
        "title": "The Promised Day",
    }
    assert metadata_job._capture(kwdict) is True
    assert metadata_job._titles_box[0] == {("S", "12"): "The Promised Day"}


def test_capture_without_title_still_returns_true(metadata_job) -> None:
    # Title absence must not force a child-extractor descent.
    kwdict = {"manga": "S", "chapter": 3, "date": datetime(2026, 1, 5)}
    assert metadata_job._capture(kwdict) is True
    assert metadata_job._titles_box[0] == {}


def test_capture_ignores_title_when_manga_missing(metadata_job) -> None:
    # For series-level kwdicts `title` can be the series name, not a chapter
    # title — only bank it when it's keyed to a (manga, chapter) pair.
    kwdict = {"title": "Series Name Itself", "chapter": ""}
    metadata_job._capture(kwdict)
    assert metadata_job._titles_box[0] == {}
```

(Adapt the `metadata_job` fixture spelling to how existing tests construct
the sim job; mirror them.)

Also add a fake-side test:

```python
def test_fake_gallery_extract_metadata_returns_titles() -> None:
    config = FakeGalleryConfig()
    config.chapter_dates_for["https://example/x"] = {("S", "1"): "2026-01-01"}
    config.chapter_titles_for["https://example/x"] = {("S", "1"): "Intro"}
    gallery = FakeGallery(Settings(data_dir=Path("/tmp/unused")), config=config)
    meta = gallery.extract_metadata("https://example/x")
    assert meta.chapter_titles == {("S", "1"): "Intro"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/downloads/test_gallery.py -v`
Expected: FAIL — `_titles_box` / `chapter_titles` don't exist.

- [ ] **Step 3: Implement**

In `MetadataResult`, add below `chapter_dates` (and document it in the
docstring: same key shape as `chapter_dates`; absent key = source exposed no
title):

```python
    chapter_titles: dict[tuple[str, str], str] = field(default_factory=dict)
```

In `_MetadataSimulationJob`: add `_titles_box: list[dict[tuple[str, str], str]]`
to the class attrs, to the `_inherit_shared_state` call, and `[{}]` to the
fresh-init branch. In `_capture`, after `chapter = chapter_with_minor(kwdict)`
is computed (reuse the existing `manga` / `chapter` locals — don't recompute):

```python
        if manga and chapter:
            title = kwdict.get("title")
            if isinstance(title, str) and title.strip():
                self._titles_box[0].setdefault((manga, chapter), title.strip())
```

Keep the final `if manga and chapter and date:` return criterion untouched.

In `Gallery.extract_metadata`, add to the returned `MetadataResult`:

```python
            chapter_titles=dict(job._titles_box[0]),
```

In `tests/fakes.py`: add to `FakeGalleryConfig.__init__`

```python
        # Optional per-URL chapter-title map surfaced by extract_metadata.
        # Keys are (manga, chapter) tuples, values are title strings.
        self.chapter_titles_for: dict[str, dict[tuple[str, str], str]] = {}
```

and in `FakeGallery.extract_metadata` add
`chapter_titles=dict(self._config.chapter_titles_for.get(url, {}))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/downloads/test_gallery.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/src/backend/downloads/gallery.py backend/tests/fakes.py backend/tests/downloads/test_gallery.py
git commit -m "feat(downloads): capture per-chapter titles in the metadata sim pass"
```

---

## Task 2: Thread titles through ChapterSeed and reconcile_outcomes

**Files:**
- Modify: `backend/src/backend/downloads/outcomes.py`
- Test: `backend/tests/downloads/test_outcomes.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_skipped_chapter_keeps_seed_title() -> None:
    needed = [ChapterSeed(name="3", date="2026-03-03", title="Calm Before")]
    out = reconcile_outcomes(needed, [], {}, exit_code=0)
    assert out[0].status == "skipped"
    assert out[0].title == "Calm Before"


def test_failed_chapter_keeps_seed_title() -> None:
    needed = [ChapterSeed(name="7", date="", title="Storm")]
    out = reconcile_outcomes(needed, [], {"7": "403"}, exit_code=1)
    assert out[0].title == "Storm"


def test_downloaded_chapter_prefers_record_title_over_seed() -> None:
    needed = [ChapterSeed(name="1", date="", title="Seeded")]
    records = [_rec("1", "001.jpg", title="From Download")]
    out = reconcile_outcomes(needed, records, {}, exit_code=0)
    assert out[0].title == "From Download"


def test_downloaded_chapter_falls_back_to_seed_title() -> None:
    needed = [ChapterSeed(name="1", date="", title="Seeded")]
    records = [_rec("1", "001.jpg")]  # record has no title
    out = reconcile_outcomes(needed, records, {}, exit_code=0)
    assert out[0].title == "Seeded"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/downloads/test_outcomes.py -v`
Expected: FAIL — `ChapterSeed` has no `title`.

- [ ] **Step 3: Implement**

Add `title: str = ""` to `ChapterSeed` (default keeps existing positional
constructions valid). In `reconcile_outcomes`:

- `_downloaded` gains a `title_fallback: str = ""` parameter mirroring
  `date_fallback`, used as `_first((r.title for r in recs), title_fallback)`;
  pass `seed.title` at the call site.
- The `skipped` and `failed` branches construct outcomes with `seed.title`
  instead of `""`.

- [ ] **Step 4: Run tests, commit**

Run: `cd backend && uv run pytest tests/downloads/test_outcomes.py -v`

```bash
git add backend/src/backend/downloads/outcomes.py backend/tests/downloads/test_outcomes.py
git commit -m "feat(downloads): carry seeded chapter titles through outcome reconciliation"
```

---

## Task 3: Persist seeded titles in the manifest

**Files:**
- Modify: `backend/src/backend/downloads/service.py` (`save_manifest` ~90-119,
  `save_chapter_outcomes` ~132-177)
- Test: `backend/tests/downloads/test_service.py`

- [ ] **Step 1: Write the failing tests**

```python
async def test_save_manifest_persists_titles(db: aiosqlite.Connection) -> None:
    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(
        db, d.id, ["1", "2"], titles={"1": "Intro"}, discovered=2
    )
    outcomes = await service.get_chapter_outcomes(db, d.id)
    by_name = {o.name: o for o in outcomes}
    assert by_name["1"].title == "Intro"
    assert by_name["2"].title == ""


async def test_outcome_with_empty_title_does_not_blank_seeded_title(
    db: aiosqlite.Connection,
) -> None:
    from backend.downloads.outcomes import ChapterOutcome

    d = await service.insert_pending(db, "https://example/x", "fake")
    await service.save_manifest(db, d.id, ["1"], titles={"1": "Seeded"})
    await service.save_chapter_outcomes(
        db, d.id, [ChapterOutcome("1", "skipped", 0, "", "", None)]
    )
    outcomes = await service.get_chapter_outcomes(db, d.id)
    assert outcomes[0].title == "Seeded"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/downloads/test_service.py -k title -v`

- [ ] **Step 3: Implement**

`save_manifest` gains `titles: dict[str, str] | None = None`; the INSERT
becomes:

```python
        await db.executemany(
            "INSERT INTO download_files(download_id, idx, relpath, status, date, title) "
            "VALUES(?, ?, ?, 'pending', ?, ?)",
            [
                (download_id, i, name, dates.get(name, ""), titles.get(name, ""))
                for i, name in enumerate(chapter_names)
            ],
        )
```

(with `titles = titles or {}` alongside the existing `dates` default).

In `save_chapter_outcomes`, change the UPDATE's `title = ?` to
`title = COALESCE(NULLIF(?, ''), title)` — identical pattern to the `date`
column on the next clause.

Note: task 3 already makes reconciliation thread seed titles into outcomes,
so the COALESCE is belt-and-braces for direct callers and legacy rows.

- [ ] **Step 4: Run tests, commit**

Run: `cd backend && uv run pytest tests/downloads/test_service.py -v`

```bash
git add backend/src/backend/downloads/service.py backend/tests/downloads/test_service.py
git commit -m "feat(downloads): persist seeded chapter titles on manifest rows"
```

---

## Task 4: Worker threads titles into seeds and the manifest

**Files:**
- Modify: `backend/src/backend/downloads/worker.py`
  (`_extract_metadata` ~287-308, `_process` save_manifest call ~223-229,
  `_filter_needed_chapters` ~482-497)
- Test: `backend/tests/downloads/test_worker.py`

- [ ] **Step 1: Write the failing test**

Mirror `test_worker_persists_per_chapter_outcomes`'s fixture usage:

```python
async def test_worker_seeds_chapter_titles_from_metadata_pass(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    config.chapter_dates_for["https://example/x"] = {
        ("S", "1"): "2026-01-01",
        ("S", "2"): "2026-01-02",
    }
    config.chapter_titles_for["https://example/x"] = {
        ("S", "1"): "Intro",
        ("S", "2"): "Rising Action",
    }
    # Nothing downloads (clean exit, no records): both chapters settle as
    # skipped — exactly the case where titles used to be lost.
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        d = await downloads_service.insert_pending(db, "https://example/x", "fake")
        worker.notify()
        await _wait_for_terminal(db, d.id)
        outcomes = await downloads_service.get_chapter_outcomes(db, d.id)
        by_name = {o.name: o for o in outcomes}
        assert by_name["1"].title == "Intro"
        assert by_name["2"].title == "Rising Action"
    finally:
        await worker.stop()
```

(Use the file's existing wait helper; `_wait_for_terminal` here is a stand-in
for whatever the file already defines.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_worker.py -k titles -v`

- [ ] **Step 3: Implement**

- `_filter_needed_chapters(chapter_dates, chapter_titles, skip_chapter)`:
  pass `title=chapter_titles.get((manga, chapter), "")` when building each
  `ChapterSeed`.
- `_extract_metadata`: call it as
  `_filter_needed_chapters(meta.chapter_dates, meta.chapter_titles, skip_chapter)`.
- `_process`: extend the `save_manifest` call with
  `titles={s.name: s.title for s in needed if s.title}`.

- [ ] **Step 4: Run the worker suite, commit**

Run: `cd backend && uv run pytest tests/downloads/test_worker.py tests/test_worker_resilience.py -v`

```bash
git add backend/src/backend/downloads/worker.py backend/tests/downloads/test_worker.py
git commit -m "feat(downloads): seed manifest chapter titles from the metadata pass"
```

---

## Task 5: Progress endpoint surfaces titles for in-flight jobs

Terminal jobs already serve titles via `_progress_from_outcomes`. The
non-terminal path (`_legacy_progress`) builds rows from bare names; align it.

**Files:**
- Modify: `backend/src/backend/downloads/router.py` (`get_progress` ~150-178,
  `_legacy_progress` ~181-199)
- Test: `backend/tests/downloads/test_router.py`

- [ ] **Step 1: Write the failing test**

Use the file's established pattern for holding a job in the running state
(`FakeGalleryConfig` has a per-URL gate event for exactly this — see its
docstring) and assert the progress payload while the job is mid-flight:

```python
    prog = client.get(f"/api/downloads/{job_id}/progress").json()
    titles = {c["name"]: c["title"] for c in prog["chapters"]}
    assert titles["1"] == "Intro"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/downloads/test_router.py -k title -v`
Expected: FAIL — `title` is `None` on the legacy path.

- [ ] **Step 3: Implement**

In `get_progress`, the non-terminal branches currently derive `manifest`
(names) via `service.get_manifest`. Fetch
`outcomes = await service.get_chapter_outcomes(db, download.id)` instead,
derive `manifest = [o.name for o in outcomes]` for the two
`chapter_progress*` calls, and pass `outcomes` into `_legacy_progress`. There,
zip by index (both lists preserve manifest order) and set
`title=outcomes[i].title or None` and `date=outcomes[i].date or None` on each
`ChapterProgress`. Guard with `i < len(outcomes)` — `chapter_progress` output
is always the same length, but keep the zip defensive.

If `service.get_manifest` has no remaining callers after this, delete it and
its tests.

- [ ] **Step 4: Run router suite, full backend check, commit**

Run: `cd backend && uv run pytest tests/downloads/test_router.py -v`
Run: `mise run lint:backend && mise run typecheck:backend && mise run test:backend`

```bash
git add backend/src/backend/downloads/router.py backend/src/backend/downloads/service.py backend/tests/downloads
git commit -m "feat(downloads): surface seeded chapter titles on live progress"
```

---

## Task 6: ProgressCard renders chapter titles

`ChapterProgress.title` is already in the generated client types (verbose
trace feature) — **no client regen needed for Phase A.** Today the title only
appears as a hover tooltip (`title={ch.title || label}` attribute,
`ProgressCard.tsx` ~239); render it as visible text.

**Files:**
- Modify: `frontend/src/components/ProgressCard.tsx` (row label, ~199-243)
- Test: `frontend/src/components/ProgressCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Extend the existing `PROGRESS` fixture's chapter entries (they already carry
`title`) and assert the title text is visible:

```tsx
  it("shows the chapter title next to its number", async () => {
    mockFetch(/* existing pattern serving PROGRESS */);
    renderWithProviders(<ProgressCard id={1} />);
    expect(await screen.findByText(/Intro/)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/components/ProgressCard.test.tsx`

- [ ] **Step 3: Implement**

In the virtualized row, change the visible label so a known title reads
`<number> — <title>` (keep the bare number when title is absent, and keep the
existing ellipsis/overflow styling — titles can be long):

```tsx
const label = ch.name || "(untitled)";
const display = ch.title ? `${label} — ${ch.title}` : label;
```

Keep `chapterKeys` keyed off `ch.name` as today (titles don't affect React
keys). The hover tooltip can stay.

- [ ] **Step 4: Run frontend checks, commit**

Run: `cd frontend && pnpm vitest run src/components/ProgressCard.test.tsx`
Run: `mise run lint:frontend && mise run typecheck:frontend`

```bash
git add frontend/src/components/ProgressCard.tsx frontend/src/components/ProgressCard.test.tsx
git commit -m "feat(ui): show chapter titles in the job chapter list"
```

---

## Task 7: Phase A checkpoint

- [ ] Run: `mise run check`
Expected: all green. This is the natural stopping point if Phase B is
deferred — Phase A is fully shippable on its own.

---

## Task 8: `targets.metadata_source_url` column (schema + migration)

**Files:**
- Modify: `backend/src/backend/database.py` (SCHEMA `targets` table ~20-34,
  `_migrate` targets block ~197-208)
- Test: `backend/tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Mirror `test_migrate_adds_verbose_trace_columns`: open a fresh DB, assert
`"metadata_source_url"` is in `PRAGMA table_info(targets)` columns; re-open to
confirm idempotency (the existing idempotency test pattern).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_database.py -k metadata_source -v`

- [ ] **Step 3: Implement**

Add `metadata_source_url TEXT` to the `targets` CREATE TABLE (after
`series_published_at TEXT`), and to `_migrate`'s targets block:

```python
    if "metadata_source_url" not in target_cols:
        await db.execute("ALTER TABLE targets ADD COLUMN metadata_source_url TEXT")
```

- [ ] **Step 4: Run tests, commit**

```bash
git add backend/src/backend/database.py backend/tests/test_database.py
git commit -m "feat(db): add targets.metadata_source_url column"
```

---

## Task 9: Target schema, service update, and PATCH validation

**Files:**
- Modify: `backend/src/backend/targets/schemas.py` (`Target`, `TargetUpdate`)
- Modify: `backend/src/backend/targets/service.py` (`update`, the `upsert`
  fresh-row construction ~107-121 — new field defaults to `None`)
- Modify: `backend/src/backend/targets/router.py` (`update_target` ~44-127)
- Test: `backend/tests/targets/test_service.py`, `backend/tests/targets/test_router.py`

- [ ] **Step 1: Write the failing tests**

Service level:

```python
async def test_update_sets_and_clears_metadata_source_url(db) -> None:
    t = await service.upsert(db, "https://example/s", "fake", None)
    updated = await service.update(db, t.id, metadata_source_url="https://mangadex.org/title/abc")
    assert updated is not None
    assert updated.metadata_source_url == "https://mangadex.org/title/abc"
    cleared = await service.update(db, t.id, metadata_source_url=None)
    assert cleared is not None
    assert cleared.metadata_source_url is None
```

Router level (mirror the file's existing PATCH tests; the test client's fake
gallery resolves extractors via `extractor_for` / `default_extractor`):

- PATCH with a URL the gallery recognises → 200, field set.
- PATCH with `""` → 200, field cleared.
- PATCH with a URL the fake's `find_extractor` returns `None` for → 400.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/targets -v`

- [ ] **Step 3: Implement**

- `Target`: add `metadata_source_url: str | None = None`.
- `TargetUpdate`: add `metadata_source_url: str | None = None` with the
  comment `# Empty string clears.`
- `service.update`: add `metadata_source_url: str | None | Unset = UNSET`
  following the exact pattern of `series_status`.
- `service.upsert`: add `metadata_source_url=None` to the fresh-`Target`
  construction (the DB row simply omits the column → NULL).
- Router: in `update_target`, follow the `series_status` block's shape.
  Validation needs extractor detection — check how the downloads submit
  endpoint resolves its gallery dependency (`backend/dependencies.py` /
  `downloads/dependencies.py`) and use the same dependency here so tests
  exercise the fake. Reject (400) when `find_extractor(url)` returns `None`:
  `f"no gallery-dl extractor matches {url!r}"`.

- [ ] **Step 4: Run tests, commit**

Run: `cd backend && uv run pytest tests/targets -v`

```bash
git add backend/src/backend/targets backend/tests/targets
git commit -m "feat(targets): per-target metadata source URL"
```

---

## Task 10: Worker fallback — fill missing titles from the metadata source URL

**Files:**
- Modify: `backend/src/backend/downloads/worker.py` (`_extract_metadata`)
- Test: `backend/tests/downloads/test_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
async def test_worker_fills_titles_from_metadata_source_url(
    settings: Settings, db: aiosqlite.Connection
) -> None:
    config = FakeGalleryConfig()
    # Original source: dates but no titles.
    config.chapter_dates_for["https://example/x"] = {("S", "1"): "2026-01-01"}
    # Alternate source: same chapter numbers under a different series name.
    config.chapter_dates_for["https://alt/x"] = {("S Alt", "1"): "2026-01-01"}
    config.chapter_titles_for["https://alt/x"] = {("S Alt", "1"): "Intro"}
    gallery = FakeGallery(settings, config=config)
    worker = Worker(db, gallery, LiveProgress())  # type: ignore[arg-type]
    worker.start()
    try:
        target = await targets_service.upsert(db, "https://example/x", "fake", None)
        await targets_service.update(db, target.id, metadata_source_url="https://alt/x")
        d = await downloads_service.insert_pending(
            db, "https://example/x", "fake", target_id=target.id
        )
        worker.notify()
        await _wait_for_terminal(db, d.id)
        outcomes = await downloads_service.get_chapter_outcomes(db, d.id)
        assert outcomes[0].title == "Intro"
        # The secondary pass actually ran:
        assert "https://alt/x" in gallery.metadata_calls
    finally:
        await worker.stop()
```

Add two negative tests:
- titles already complete from the original source → `https://alt/x` is
  **not** in `gallery.metadata_calls` (no wasted upstream fetch);
- secondary `extract_metadata` raising (FakeGallery: add a per-URL
  `metadata_error_for` raise hook if one doesn't exist) → download still
  completes, titles just stay empty.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/downloads/test_worker.py -k metadata_source -v`

- [ ] **Step 3: Implement**

At the end of `_extract_metadata`, after `needed` is computed:

```python
        needed = await self._fill_titles_from_metadata_source(job, needed)
        return needed, len(meta.chapter_dates)
```

New private method:

```python
    async def _fill_titles_from_metadata_source(
        self, job: Download, needed: list[ChapterSeed]
    ) -> list[ChapterSeed]:
        """Fill-only title lookup against the target's metadata_source_url.

        Runs at most one extra extract_metadata, and only when some needed
        chapter still lacks a title. Titles match by chapter number alone —
        the alternate source's series name will differ. Best-effort: any
        failure logs a warning and leaves the seeds untouched.
        """
        if job.target_id is None or all(s.title for s in needed) or not needed:
            return needed
        target = await targets_service.get(self._db, job.target_id)
        if target is None or not target.metadata_source_url:
            return needed
        try:
            alt = await asyncio.to_thread(
                self._gallery.extract_metadata, target.metadata_source_url
            )
        except Exception:
            logger.warning(
                "metadata source lookup failed for target %d (%s)",
                job.target_id,
                target.metadata_source_url,
                exc_info=True,
            )
            return needed
        titles_by_chapter = {ch: t for (_m, ch), t in alt.chapter_titles.items()}
        return [
            replace(s, title=titles_by_chapter.get(s.name, "")) if not s.title else s
            for s in needed
        ]
```

(`from dataclasses import replace` at the top.) Note the cancel-flag check in
`_process` happens right after `_extract_metadata` returns, so a cancel
during the secondary fetch is still honoured before the manifest is saved.

- [ ] **Step 4: Run tests, full backend check, commit**

Run: `mise run lint:backend && mise run typecheck:backend && mise run test:backend`

```bash
git add backend/src/backend/downloads/worker.py backend/tests/downloads/test_worker.py backend/tests/fakes.py
git commit -m "feat(downloads): fill missing chapter titles from the target's metadata source"
```

---

## Task 11: Regenerate the typed frontend client

`Target` / `TargetUpdate` gained `metadata_source_url`.

- [ ] **Step 1:** Boot the backend, regenerate, stop it — follow the exact
  recipe in `docs/superpowers/plans/2026-06-08-verbose-job-trace.md` Task 9
  (uvicorn on :8000, `mise run generate:client`, kill).
- [ ] **Step 2:** Verify: `cd frontend && rg -n "metadata_source_url" src/api/types.gen.ts`
- [ ] **Step 3:** `mise run typecheck:frontend`, then:

```bash
git add frontend/src/api
git commit -m "chore(api): regenerate client for target metadata_source_url"
```

---

## Task 12: Target edit UI — metadata source URL field

**Files:**
- Modify: `frontend/src/components/TargetRow.tsx` (inspect first: find where
  `series_status` / `reading_direction` / `tags` are edited and mirror that
  exact pattern — same PATCH mutation, same save/cancel affordances)
- Test: `frontend/src/components/TargetsList.test.tsx` or the TargetRow-level
  test file, whichever covers the existing editable fields

- [ ] **Step 1: Write the failing test** — render the target editor with a
  target carrying `metadata_source_url`, assert the input shows it; simulate
  editing and assert the PATCH body includes the new value (mirror the
  existing series-status edit test).
- [ ] **Step 2:** Run: `cd frontend && pnpm vitest run src/components/`
- [ ] **Step 3: Implement** — a `TextInput` labelled
  `Metadata source URL` with description copy along the lines of
  `Optional. Another site for this series (e.g. MangaDex) used to look up chapter names when this source has none.`
  Empty submits as `""` (backend clears). Follow the existing field order /
  spacing in the edit surface.
- [ ] **Step 4:** Run: `mise run lint:frontend && mise run typecheck:frontend && mise run test:frontend`

```bash
git add frontend/src/components
git commit -m "feat(ui): edit a target's metadata source URL"
```

---

## Task 13: Final verification

- [ ] Run: `mise run check`
- [ ] Run the e2e suite if configured in CI (`frontend/e2e`): follow whatever
  `mise tasks` exposes for it; update `frontend/e2e/downloads.spec.ts`
  expectations only if the chapter-label change broke a selector.
- [ ] Push and open the PR (rebase-merge repo; set auto-merge per repo
  convention).

---

## Out of scope (deliberately)

- **Direct MangaDex REST client.** Reusing gallery-dl extractors via
  `metadata_source_url` covers the same ground with zero new HTTP surface; a
  bespoke client (auth, rate limits, ID matching) can be a follow-up if
  extractor coverage proves insufficient.
- **Backfilling titles into historical `download_files` rows.** The manifest
  is a per-run trace; old runs stay as they were. A maintenance job could do
  this later using the same `_fill_titles_from_metadata_source` logic.
- **A persisted per-target chapter list (`target_chapters` table).** Nothing
  in the UI needs a chapter list outside a download's manifest yet.
- **Preferred-language selection for titles.** gallery-dl extractor config
  governs which translation is enumerated; good enough until someone asks.
