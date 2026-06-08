# Verbose per-job download trace — design

**Date:** 2026-06-08
**Status:** Approved (design), pending implementation
**Branch:** `feat/verbose-job-trace`

## Problem

Job output is too thin to trace what a download actually did. The user wants to
see, per job and *on the past-job screen*, things like the current (discovered)
chapter count, how many chapters needed downloading, how many actually
downloaded, and which ones failed and why.

### Why the information is missing today

The system already *computes* most of this and then discards it:

- `worker._extract_metadata` has `meta.chapter_dates` — the full **discovered**
  chapter set — but only keeps `chapter_names` (the **needed** set after the
  watched-target skip filter). The discovered total is dropped
  (`backend/src/backend/downloads/worker.py:198-218`).
- `_execute_download` builds rich `FileRecord`s (manga, chapter, title, date,
  pages-by-dir) and a `chapters_seen` set, then keeps only a single count
  (`files_downloaded`) (`worker.py:220-253`).
- Per-chapter progress lives only in the in-memory `LiveProgress`, which the
  worker **clears the instant a job ends** (`worker.py:151`,
  `downloads/live_progress.py:24`).
- Consequently, for any terminal job the progress endpoint falls back to
  `chapter_progress()`, which blindly stamps **every** chapter `"completed"`
  (`downloads/router.py:159`, `downloads/progress.py:50-56`). Past jobs cannot
  report what really happened — the truth was never written down.

Per-chapter download **failures** are never captured at all: gallery-dl logs
them to stderr → systemd journal globally, not per job.

## Goals

1. Persist a structured, per-job trace that **survives to the history screen**.
2. Surface headline counts: chapters **discovered** / **needed** /
   **downloaded** / **failed**.
3. Capture **per-chapter outcome** (downloaded / skipped / failed) with
   per-chapter detail: pages, title, date, and a failure **reason**.

## Non-goals (YAGNI)

- No raw gallery-dl log capture / per-job log viewer (declined; structured only).
- No elaborate skip-source attribution (app-level "already packed" vs
  gallery-dl archive skip). "Already had" is the self-evident
  `discovered − needed` gap.
- No continuous mid-flight persistence of progress; live progress stays
  in-memory, outcomes are persisted at terminal transitions (snapshot model).

## Key enabling facts (verified in code)

- **Reliable chapter key.** Both the metadata sim (`gallery.py:232`) and the
  download's `FileRecord.chapter` (`gallery.py:132` →
  `postprocess.coerce_record_from_kwdict`) derive the chapter via the *same*
  `chapter_with_minor(kwdict)`. Records reconcile to manifest rows by exact
  string match — no need for the current fragile order-based mapping
  (`progress.py:77`).
- **Failure capture is concurrency-safe.** The `Worker` is strictly serial —
  "one job in flight, ever" (`worker.py:34`). A process-global logging handler
  attached around `job.run()` therefore only ever serves one job, so bucketing
  WARNING/ERROR records to the current chapter needs no locking.

## Design

### 1. Data model

**`downloads`** — two new (nullable) columns, denormalized so the list view
(`service.list_recent`) stays a single query:

- `chapters_discovered INTEGER` — total chapters found by the metadata pass,
  *before* skip-filtering.
- `chapters_failed INTEGER` — needed chapters that produced no files.

Existing columns keep their meaning: `chapters_total` / `files_expected` =
chapters **needed**; `files_downloaded` = chapters **downloaded**.

**`download_files`** — already one row per needed chapter
(`service.save_manifest`, `database.py:56-63`). New columns:

- `status TEXT` — `pending` → `downloaded` | `skipped` | `failed`
- `pages INTEGER` — files landed in the chapter dir
- `title TEXT` — chapter title (from `FileRecord.title`)
- `date TEXT` — chapter date, ISO (from `chapter_dates` / `FileRecord.date`)
- `error TEXT` — failure reason; NULL otherwise

`relpath` stays the chapter-name key. Columns are added through the existing
idempotent `_migrate` pattern (`database.py:112`). Pre-feature rows keep
`status = NULL`; the progress endpoint renders those with today's neutral
behavior (no retroactive lying).

### 2. Backend capture flow

**Discovered count + dates at manifest time.** `_extract_metadata` returns the
needed chapters *and* the discovered total and per-chapter dates. `save_manifest`
is extended to accept `(chapter_name, date)` pairs + the discovered count,
writing rows as `status='pending'` with `date` set and
`downloads.chapters_discovered`.

**Per-chapter failure reasons (scoped error-log capture).** A small
`ChapterErrorCollector` `logging.Handler` is attached to gallery-dl's logger
around `job.run()` in `Gallery.run_download` (installed/removed in a
`try/finally`). `_ProgressDownloadJob` tracks the current chapter in a shared
mutable box, set in a `handle_directory` override via `chapter_with_minor`; the
collector tags each captured WARNING/ERROR record with the current chapter.
`run_download` returns `(exit_code, records, chapter_errors)` where
`chapter_errors: dict[str, str]` maps chapter → reduced reason string.

**Reconciliation at finish** (`_execute_download`):

- Group `records` by `FileRecord.chapter` → `pages` (count), `title`, `date`.
- For each needed manifest chapter:
  - has records → `downloaded` (+ pages/title/date)
  - else in `chapter_errors` → `failed` (+ reason)
  - else clean exit (`exit_code == 0`), no records → `skipped` (archive already
    had the files)
  - else → `failed` (reason unknown)
- Persist via new `service.save_chapter_outcomes(download_id, outcomes)`, which
  also sets `downloads.chapters_failed` and `files_downloaded`.

**Robustness.** When `chapter_dates` is empty (date-less extractors) but files
still download, synthesize outcome rows from `records` so the trace isn't blank.
Cancel / failure paths persist partial outcomes best-effort.

**Lifecycle cleanup.** `reset_to_pending` and `delete_all` already clear/cascade
`download_files`; ensure the new `downloads` columns reset on requeue.

### 3. API + schemas

- `Download`: `+ chapters_discovered: int | None`, `+ chapters_failed: int | None`.
- `ChapterProgress`: `+ status`, `+ pages`, `+ title`, `+ date`, `+ error`
  (existing `name` / `files_total` / `files_present` / `stage` retained for the
  live path).
- `ProgressOut`: `+ chapters_discovered / needed / downloaded / failed / skipped`.
- **`get_progress`**: for terminal jobs, build the chapter list from the
  persisted `download_files` rows instead of the `chapter_progress()`
  "everything completed" fallback (`router.py:159`). Live jobs keep the
  in-memory snapshot path.
- Regenerate the typed frontend client (hey-api OpenAPI codegen) after the
  schema change — `frontend/src/api/types.gen.ts` and
  `@tanstack/react-query.gen.ts` are generated.

### 4. Frontend display

- **`ProgressCard`**: a summary line
  (`discovered 30 · needed 5 · downloaded 4 · failed 1`) plus per-chapter rows
  gaining `downloaded` / `skipped` / `failed` badges (failed = red, reason in
  tooltip) with pages + date as secondary text. Works for past jobs now that the
  endpoint returns persisted truth.
- **`RecentRow`**: extend `chapterCountLabel`, e.g. `4/5 ch. · 1 failed`.
- **`lib/status.ts`**: tones + labels for the new chapter stages.

### 5. Testing

Backend (pytest):
- Reconciliation: records → outcomes (downloaded/skipped/failed split).
- `ChapterErrorCollector`: WARNING/ERROR records bucket to the current chapter.
- Migration adds the new columns idempotently.
- `save_manifest` (discovered + dates) and `save_chapter_outcomes`.
- **Regression (headline):** progress endpoint returns real per-chapter truth
  for a terminal job (not "all completed").

Frontend (vitest):
- `ProgressCard` renders failed/skipped badges + the summary line.
- `RecentRow` label with a failed count.

## Risks / open caveats

- `chapters_discovered` inherits the metadata pass's extractor-dependent
  reliability: extractors that only surface dates on the chapter page yield an
  empty `chapter_dates`, so discovered may be 0 even when files download. The
  record-synthesis fallback keeps the per-chapter trace correct in that case; the
  discovered headline is best-effort and documented as such.
- The `skipped` vs `failed` split for clean-exit-no-record chapters is a
  heuristic; the scoped error capture should catch genuine failures, leaving
  archive-skips as the clean no-record case.
