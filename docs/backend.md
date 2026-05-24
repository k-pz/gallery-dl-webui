# Backend

The FastAPI app, its lifespan, settings, database schema, and per-domain
module shape. The actual download flow (worker → gallery-dl → postprocess
→ progress) lives in [Download pipeline](pipeline.md).

## Application factory and lifespan

`backend/src/backend/main.py`

`create_app(settings_factory, gallery_factory, serve_frontend)` builds the
FastAPI app. Both factories are injectable so tests can plug in stub
`Settings` and a `FakeGallery` without monkey-patching.

The `lifespan` async context manager runs at startup:

1. Ensure `data_dir` and `downloads_dir` exist (`mkdir -p`).
2. `open_database(settings.jobs_db_path)` — install schema + run migrations.
3. Construct `Gallery(settings)`, which configures gallery-dl's process-global
   state (`base-directory`, `archive` path).
4. `mark_interrupted_on_boot(db)` — flip any rows still stuck in
   `extracting`/`running` from a previous run to `failed`. Logged as a
   warning.
5. Construct `LiveProgress`, `Worker`, `Poller`. Start the worker, then the
   poller.
6. Stash everything on `app.state` so `dependencies.py` deps can find it.
7. Yield. On shutdown: stop the poller, stop the worker, close the DB.

`/api/...` routes are mounted via `include_router(..., prefix="/api")`. When
`serve_frontend=True` (production) the SPA is served from `FRONTEND_DIST` with
an `/assets` `StaticFiles` mount plus a wildcard SPA fallback. When false
(dev/test) CORS is opened to `http://localhost:5173`.

## Settings

`config.py` is dataclass-only.

| Env var          | Default      | Used for                                    |
|------------------|--------------|---------------------------------------------|
| `WEBUI_DATA_DIR` | `<repo>/data`| `jobs.db`, `archive.db`, `downloads/`       |
| `WEBUI_HOST`     | `0.0.0.0`    | uvicorn bind                                |
| `WEBUI_PORT`     | `8000`       | uvicorn bind                                |

Per-domain knobs (postprocess root, default watch period, delete-raw) are
*not* env-driven — they live in the `app_config` SQLite table so the UI can
edit them at runtime.

## Database

`database.py` owns the entire SQLite schema and migration logic. One
`aiosqlite.Connection` is opened at startup and shared by every service.

Tables:

```
targets
  id, url (UNIQUE), name, extractor, output_dir,
  watched (0/1), watch_period, last_polled_at, created_at,
  tags (JSON), reading_direction, series_status

downloads
  id, url, extractor, status, created_at, started_at, finished_at,
  exit_code, files_downloaded, files_expected, chapters_total, error,
  postprocess_status, postprocess_chapters_packed, postprocess_error,
  output_dir, target_id (FK → targets.id)

download_files          ← the per-job manifest
  download_id (FK), idx, relpath
  PRIMARY KEY (download_id, idx)

app_config              ← key/value, JSON-encoded value column
  key PRIMARY KEY, value
```

Indexes are created idempotently. Migrations are forward-only `ADD COLUMN`s
guarded by `PRAGMA table_info(...)`. When the `target_id` column was added,
`_backfill_targets` retroactively created `targets` rows for every distinct
URL seen in existing `downloads` rows and linked them — so an old install
upgrades cleanly with no manual SQL.

`gallery-dl`'s own `archive.db` is a separate SQLite file that gallery-dl
manages itself; the backend never opens it. Its job is to make sure
gallery-dl skips files it has already downloaded.

## Per-domain modules

Each domain folder follows the same shape:

```
<domain>/
  router.py        ← APIRouter, route handlers, request validation
  service.py       ← SQL operations on this domain's tables
  schemas.py       ← Pydantic models — used both as the internal row shape
                     and as the wire DTO. `Foo.from_row(row)` constructs
                     from a SELECT; `FooCreate` / `FooUpdate` cover I/O-only
                     shapes that don't round-trip a row.
  dependencies.py  ← FastAPI Depends() callables (e.g. valid_<id> lookups)
  exceptions.py    ← domain-specific HTTPException subclasses
  constants.py     ← status taxonomies, defaults, limits
```

Cross-domain calls always go service-to-service (`from backend.targets import
service as targets_service`). Routers don't import other routers.

### downloads/

The biggest domain by far. End-to-end:

1. **`POST /api/downloads`** (`router.create_download`):
   - Trim URL, ask gallery-dl which extractor matches (`Gallery.find_extractor`
     → 400 if unsupported).
   - If `output_dir` provided, look up the postprocess root from `app_config`
     and validate the path is under it (`validate_under_root`, which also
     `mkdir -p`s and write-probes). Remember the dir in
     `app_config.postprocess_known_output_dirs` for autocomplete.
   - `targets_service.upsert(...)` — creates a `targets` row for this URL
     if none exists, otherwise refreshes its `extractor` / `output_dir` from
     the latest submit.
   - `service.insert_pending(...)` writes a `downloads` row with
     `status='pending'`.
   - `worker.notify()` — sets the wakeup event so the loop picks up the new row.

2. **`GET /api/downloads`** — recent 50 rows, each with `name` joined from
   the target.

3. **`GET /api/downloads/{id}`** — single download. The `DownloadDep` dep
   raises 404 if missing.

4. **`POST /api/downloads/{id}/cancel`** — refuses if terminal (`completed/
   failed/cancelled`, 409). Otherwise sets the worker's cancel flag (best
   effort: only matches if this is the *currently running* job) AND
   atomically tries to flip the row from `pending` → `cancelled`. Returns
   the fresh row.

5. **`POST /api/downloads/{id}/requeue`** — only valid on terminal rows.
   `reset_to_pending(...)` nulls every result column AND deletes the
   `download_files` manifest so the next run re-extracts.

6. **`GET /api/downloads/{id}/progress`** — see
   [Progress accounting](pipeline.md#progress-accounting).

`service.py` exposes:

- `insert_pending`, `get`, `list_recent`, `claim_next_pending` (the worker's
  FIFO pick).
- `save_manifest`/`get_manifest` over `download_files`. Also writes
  `files_expected` and `chapters_total` (distinct parent dirs).
- State transitions: `mark_running`, `finish_job`, `mark_failed`,
  `cancel_pending` (only if still pending), `mark_cancelled`,
  `reset_to_pending`, `mark_interrupted_on_boot`, `mark_postprocess`.
- `has_active_for_target(target_id)` — the guard the poller and the
  delete-target / poll-target routes use to avoid running two downloads for
  the same target concurrently.

Status taxonomy (`constants.py`):

```
ACTIVE_STATUSES   = {"pending", "extracting", "running"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
```

Transitions:

```
pending ──── worker.claim_next_pending ───► extracting
extracting ── worker._extract_manifest done ► running
running ──── exit_code 0 ──► completed
running ──── exit_code ≠ 0 / Exception ─► failed
running ──── cancel flag observed ─► cancelled
pending ──── route cancel_pending ─► cancelled (atomic, only if still pending)
{terminal} ── route requeue ─► pending  (manifest cleared)
```

`postprocess_status`: `null` (never ran) | `running` | `completed` | `skipped`
| `failed`. Decoupled from the download status — a download is `completed`
even if postprocessing then fails.

### targets/

A target is a "saved URL". One target per gallery URL (UNIQUE constraint).
A target accumulates downloads over time; only one can be in-flight at a
time.

- `service.upsert(url, extractor, output_dir)` — find-or-create; updates
  `extractor`/`output_dir` from the latest submit. Series `name` is captured
  later by the worker from gallery-dl metadata.
- `service.list_all` / `get_summary` — uses a `LEFT JOIN ... LIMIT 1`
  subquery to attach the most-recent download's id/status/finished_at to
  each target, plus a `COUNT(*)` over downloads.
- `service.update(id, *, watched, watch_period, output_dir, tags,
  reading_direction, series_status)` — sentinel-typed optional updates so
  `None` can mean "leave it" or "clear it" depending on field (see `Unset`
  in `service.py`).
- `service.set_name(id, name)` — captured by the worker from the simulation
  pass and again, more authoritatively, from the real download.
- `service.set_series_status(id, status)` — fill-only: writes the
  auto-detected publication status from the sim pass when (and only when)
  the existing row value is blank. A user PATCH always wins because of
  that guard, so re-polling never overwrites a manual override.
- `service.set_series_tags(id, tags)` — fill-only counterpart for the
  tags/genres list surfaced by the extractor's kwdict. Same guard:
  written only when the row's `tags` column is NULL, empty, or `'[]'`.

Routes:

- `GET/PATCH/DELETE /api/targets[/{id}]`
- `POST /api/targets/{id}/poll` — manual poll: checks `has_active_for_target`,
  inserts a pending download, marks polled, wakes the worker.
- 409 on delete if there's still an active download for that target.

### targets/poller.py

A coroutine that wakes every `TICK_SECONDS` (30s) or on `.notify()` and, for
every watched target whose `last_polled_at + period` has elapsed, queues
another download (subject to `has_active_for_target`).

Per-target `watch_period` overrides the global `default_watch_period`
(`app_config`, default `"1d"`). Period strings are
`/^\s*(?:\d+\s*[smhdw]\s*)+$/i` — `30m`, `2h30m`, `1w2d`, etc. (see
`targets/utils.py::parse_duration`).

A new watch toggle (`watched: true` after being `false`) calls
`poller.notify()` so the next due check happens promptly instead of waiting
out the rest of the tick.

### app_config/

A flat `key → JSON-encoded value` table. Keys currently in use:

```
postprocess_root              str | null   ← absolute path; the upper bound
postprocess_default_output_dir str | null  ← default for new downloads
postprocess_known_output_dirs Array<str>   ← MRU autocomplete, capped at 20
delete_raw_after_pack         bool         ← default True
default_watch_period          str          ← default "1d"
```

`PUT /api/config` validates everything before persisting:

- root must be absolute; parent must exist; `mkdir -p` + write-probe.
- default output dir requires a root, and must resolve under it.
- watch period must `parse_duration`.
- If the root changes, the remembered output dirs list is cleared (the old
  paths may not be valid under the new root).

### library/

Round-trippable YAML export of the target list. Schema v1:

```yaml
version: 1
series:
  - url: https://example.com/manga/abc
    name: ABC Series
    extractor: mangadex
    output_dir: /mnt/nas/Media/manga
    watch:
      enabled: true
      period: 1d
    tags: [Action, Romance]
    reading_direction: rtl
    series_status: Ongoing
```

Import is best-effort: every series is processed independently; any single
error (invalid duration, output_dir outside root, etc.) is collected into
`LibraryImportResult.errors` rather than aborting the rest.

### output_dirs/

The directory picker on the submit form. Two endpoints:

- `GET /api/output-dirs` — list direct children of the postprocess root
  (hidden dirs filtered, sorted).
- `POST /api/output-dirs` — create a direct child of the root. Accepts
  either a bare name (`"manga"`) or a fully-qualified path
  (`"/mnt/nas/Media/manga"`); rejects nested paths.

`output_dirs/utils.py` exports the path-validation helpers used by *every*
domain that accepts a user-supplied path (`downloads`, `targets`, `library`,
`app_config`). The probe writes/unlinks `.gallery-dl-webui-write-probe` so
systemd's `ProtectSystem=strict` surfaces a missing `ReadWritePaths` whitelist
as a 400 immediately instead of failing midway through a download.

### health/

`GET /api/health` returns `{"status": "ok"}`. Used by the HealthBadge in the
UI and by Playwright as the backend's readiness probe.
