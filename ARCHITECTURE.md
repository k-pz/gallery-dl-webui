# gallery-dl-webui — Architecture & Codebase Reference

A complete map of the codebase: what each piece does, how the pieces fit
together, and the data and control flow that runs underneath the UI.

Companion to `README.md` — the README covers "how do I run it"; this document
covers "how does it actually work".

---

## 1. What it is

A small full-stack web app on top of [`gallery-dl`](https://github.com/mikf/gallery-dl).

- Submit a gallery URL in the browser, the backend extracts every file
  `gallery-dl` plans to fetch, then runs the real download in the background.
- Finished manga chapters are packed into Komga-compatible CBZ archives with
  `ComicInfo.xml` metadata.
- Targets can be marked "watched" so the backend re-polls them on a cadence.
- All state — queue, history, postprocess results, app config — lives in one
  SQLite file. The whole service is a single Python process.

Designed to run on an unprivileged Proxmox LXC behind a `systemd` unit, but is
just as happy on a laptop with `mise run dev`.

---

## 2. High-level architecture

### Process model

One uvicorn process hosts the FastAPI app. Inside that process:

```
┌──────────────────────────────── uvicorn / asyncio loop ───────────────────────────────┐
│                                                                                       │
│   FastAPI routers ──┐                                                                 │
│   (request handlers)│                                                                 │
│                     ▼                                                                 │
│              ┌──────────────┐    asyncio.Event (wakeup) ┌────────────────┐            │
│              │  Worker task │ ◄──────────────────────── │  HTTP handlers │            │
│              │ (downloads)  │ ────────────────────────► │ (notify/cancel)│            │
│              └──────┬───────┘    request_cancel(id)     └────────────────┘            │
│                     │                                                                 │
│       asyncio.to_thread( gallery-dl Sim / Download Job )                              │
│                     │                                                                 │
│              ┌──────▼─────────┐                                                       │
│              │ aiosqlite conn │  ◄── shared single connection (jobs.db)               │
│              └────────────────┘                                                       │
│                                                                                       │
│              ┌──────────────┐ TICK_SECONDS=30  + .notify() on watch-flag-on           │
│              │  Poller task │                                                         │
│              │   (watched)  │ ── inserts pending downloads for due watched targets    │
│              └──────────────┘                                                         │
│                                                                                       │
│              ┌──────────────┐                                                         │
│              │ LiveProgress │  in-memory per-download list of completed relpaths      │
│              └──────────────┘  (written from worker thread, read from HTTP handlers)  │
│                                                                                       │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

Key properties:

- **Single worker**: there is exactly one Worker coroutine; it processes one
  download at a time, in FIFO order over `downloads.id`. Concurrency comes
  later, if ever — for now the simplicity (no per-job sandbox, no rate-limit
  juggling) is the feature.
- **No background process / Celery / Redis** — the asyncio event loop is the
  only scheduler.
- **No HTTP-server lifecycle for state**: app state lives on `app.state`
  (`db`, `settings`, `gallery`, `worker`, `poller`, `live_progress`), populated
  by the FastAPI `lifespan` context manager and torn down on shutdown.
- **gallery-dl runs on a worker thread** via `asyncio.to_thread(...)`.
  Cancellation is cooperative: a bool flag the worker reads inside its
  per-file callback raises `gallery_dl.exception.StopExtraction`, which the
  gallery-dl dispatcher catches and unwinds cleanly.

### Deployment topology

```
   ┌─────────────────────────── Proxmox host ────────────────────────────┐
   │                                                                     │
   │   /mnt/lxc_shares/<host>/  ◄── CIFS mount (cifs-utils, fstab)       │
   │            │                                                        │
   │            │ pct set <CTID> -mp0 ...,mp=/mnt/nas                    │
   │            ▼                                                        │
   │   ┌──────────────── unprivileged LXC ─────────────────┐             │
   │   │                                                   │             │
   │   │   /opt/gallery-dl-webui/    (source + .venv)      │             │
   │   │   /var/lib/gallery-dl-webui/                      │             │
   │   │      ├─ jobs.db                                   │             │
   │   │      ├─ archive.db                                │             │
   │   │      └─ downloads/<extractor>/<series>/…          │             │
   │   │   /mnt/nas/Media/Manga/…    (bind-mount, NAS)     │             │
   │   │                                                   │             │
   │   │   systemd: gallery-dl-webui.service               │             │
   │   │     ExecStart=mise run -C /opt/... serve:backend  │             │
   │   │     ReadWritePaths=/var/lib/gallery-dl-webui      │             │
   │   │   + extra-rw-paths.conf drop-in for /mnt/nas/...  │             │
   │   └───────────────────────────────────────────────────┘             │
   └─────────────────────────────────────────────────────────────────────┘
```

In production the backend also serves the built React bundle from
`frontend/dist/` (mounted at `/assets` + a catch-all SPA fallback).
In dev the React dev server runs separately on `:5173` and proxies `/api/*`
to `:8000` (see `frontend/vite.config.ts`).

---

## 3. Repository layout

```
gallery-dl-webui/
├── README.md                  ← "how do I run it"
├── ARCHITECTURE.md            ← this document
├── mise.toml                  ← toolchain + tasks (python/uv/node, dev/build/test)
│
├── backend/                   ← FastAPI app (uv project, src-layout)
│   ├── pyproject.toml         ← deps: fastapi, aiosqlite, gallery-dl, pyyaml
│   ├── src/backend/
│   │   ├── main.py            ← FastAPI factory + lifespan + router registration
│   │   ├── __main__.py        ← `python -m backend` entrypoint (uvicorn)
│   │   ├── config.py          ← Settings (data_dir, host, port from env)
│   │   ├── database.py        ← aiosqlite lifecycle + schema + migrations
│   │   ├── dependencies.py    ← cross-domain FastAPI deps (db, settings)
│   │   ├── exceptions.py      ← shared HTTPException subclasses
│   │   │
│   │   ├── downloads/         ← submit / list / cancel / requeue / progress
│   │   │   ├── router.py
│   │   │   ├── service.py     ← SQL on the `downloads` / `download_files` tables
│   │   │   ├── worker.py      ← the one background coroutine
│   │   │   ├── gallery.py     ← thin wrapper + subclassed gallery-dl jobs
│   │   │   ├── postprocess.py ← CBZ packing + ComicInfo.xml
│   │   │   ├── progress.py    ← per-chapter stage derivation
│   │   │   ├── live_progress.py ← in-memory progress for in-flight downloads
│   │   │   ├── models.py / schemas.py / dependencies.py / exceptions.py / constants.py
│   │   │
│   │   ├── targets/           ← saved series; watched/poller logic
│   │   │   ├── router.py / service.py / poller.py / utils.py
│   │   │   ├── models.py / schemas.py / dependencies.py / exceptions.py
│   │   │
│   │   ├── app_config/        ← app-wide config key/value (postprocess_root, etc.)
│   │   │   ├── router.py / service.py / schemas.py / constants.py / exceptions.py
│   │   │
│   │   ├── library/           ← YAML export / import of the target list
│   │   │   └── router.py / service.py / schemas.py / constants.py
│   │   │
│   │   ├── output_dirs/       ← directory picker + path-under-root validation
│   │   │   └── router.py / service.py / utils.py / schemas.py
│   │   │
│   │   └── health/            ← /api/health
│   │
│   └── tests/
│       ├── conftest.py        ← TestClient w/ FakeGallery via create_app(...)
│       ├── fakes.py           ← FakeGallery / FakeGalleryConfig (no network)
│       ├── e2e_server.py      ← ASGI app for Playwright using the fake
│       ├── test_database.py / test_config.py
│       └── <per-domain>/test_router.py / test_service.py / ...
│
├── frontend/                  ← Vite + React + Mantine + TanStack Query
│   ├── package.json           ← scripts: dev/build/lint/test/test:e2e/generate
│   ├── vite.config.ts         ← dev server :5173, /api proxy → :8000
│   ├── playwright.config.ts   ← spawns backend+frontend on :8765/:5174 for e2e
│   ├── openapi-ts.config.ts   ← generates src/api/ from live /openapi.json
│   ├── biome.json
│   ├── index.html
│   │
│   └── src/
│       ├── main.tsx           ← Mantine + QueryClient + StrictMode wrappers
│       ├── App.tsx            ← Library / Jobs / Config tabs
│       ├── components/        ← per-feature React components
│       ├── lib/               ← status/polling/error/optimism helpers
│       ├── api/               ← *generated* by openapi-ts (do not edit)
│       └── test/              ← vitest setup
│
├── scripts/
│   ├── proxmox-install.sh     ← create LXC + bootstrap + systemd unit
│   ├── proxmox-update.sh      ← pull source, refresh deps, restart service
│   ├── proxmox-uninstall.sh   ← destroy the CT
│   └── _proxmox-lib.sh        ← shared log/die/pct helpers
│
└── data/                      ← local-dev only (gitignored): jobs.db, downloads/
```

The backend follows the "package-by-feature" / domain-modular pattern (each
domain owns its own router/service/models/schemas). Cross-domain helpers
sit at the package root (`database.py`, `dependencies.py`, `exceptions.py`).

---

## 4. Backend architecture

### 4.1 Application factory and lifespan

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

### 4.2 Settings

`config.py` is dataclass-only.

| Env var          | Default      | Used for                                    |
|------------------|--------------|---------------------------------------------|
| `WEBUI_DATA_DIR` | `<repo>/data`| `jobs.db`, `archive.db`, `downloads/`       |
| `WEBUI_HOST`     | `0.0.0.0`    | uvicorn bind                                |
| `WEBUI_PORT`     | `8000`       | uvicorn bind                                |

Per-domain knobs (postprocess root, default watch period, delete-raw) are
*not* env-driven — they live in the `app_config` SQLite table so the UI can
edit them at runtime.

### 4.3 Database

`database.py` owns the entire SQLite schema and migration logic. One
`aiosqlite.Connection` is opened at startup and shared by every service.

Tables:

```
targets
  id, url (UNIQUE), name, extractor, output_dir,
  watched (0/1), watch_period, last_polled_at, created_at

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

### 4.4 Per-domain modules

Each domain folder follows the same shape:

```
<domain>/
  router.py        ← APIRouter, route handlers, request validation
  service.py       ← SQL operations on this domain's tables
  schemas.py       ← Pydantic IO models (FooIn / FooOut / FooCreate / FooUpdate)
  models.py        ← dataclasses for internal row representations
  dependencies.py  ← FastAPI Depends() callables (e.g. valid_<id> lookups)
  exceptions.py    ← domain-specific HTTPException subclasses
  constants.py     ← status taxonomies, defaults, limits
```

Cross-domain calls always go service-to-service (`from backend.targets import
service as targets_service`). Routers don't import other routers.

#### downloads/

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

6. **`GET /api/downloads/{id}/progress`** — see [§5 Progress accounting].

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

#### targets/

A target is a "saved URL". One target per gallery URL (UNIQUE constraint).
A target accumulates downloads over time; only one can be in-flight at a
time.

- `service.upsert(url, extractor, output_dir)` — find-or-create; updates
  `extractor`/`output_dir` from the latest submit. Series `name` is captured
  later by the worker from gallery-dl metadata.
- `service.list_all` / `get_summary` — uses a `LEFT JOIN ... LIMIT 1`
  subquery to attach the most-recent download's id/status/finished_at to
  each target, plus a `COUNT(*)` over downloads.
- `service.update(id, *, watched, watch_period, output_dir)` — sentinel-typed
  optional updates so `None` can mean "leave it" or "clear it" depending on
  field (see `Unset` in `models.py`).
- `service.set_name(id, name)` — captured by the worker from the simulation
  pass and again, more authoritatively, from the real download.

Routes:

- `GET/PATCH/DELETE /api/targets[/{id}]`
- `POST /api/targets/{id}/poll` — manual poll: checks `has_active_for_target`,
  inserts a pending download, marks polled, wakes the worker.
- 409 on delete if there's still an active download for that target.

#### targets/poller.py

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

#### app_config/

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

#### library/

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
```

Import is best-effort: every series is processed independently; any single
error (invalid duration, output_dir outside root, etc.) is collected into
`LibraryImportResult.errors` rather than aborting the rest.

#### output_dirs/

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

#### health/

`GET /api/health` returns `{"status": "ok"}`. Used by the HealthBadge in the
UI and by Playwright as the backend's readiness probe.

### 4.5 The Worker

`downloads/worker.py`

A long-running coroutine driven by an `asyncio.Event` (`_wakeup`):

```
while not stop:
    job = await service.claim_next_pending(db)   # FIFO over id
    if job is None:
        await self._wakeup.wait()                # idle
        continue
    self._current_id = job.id
    self._cancel_requested = False
    try:
        await self._process(job)
    finally:
        clear cancel state
```

`_process(job)`:

1. **Build `skip_chapter` predicate** if this is a watched target with a
   resolvable output dir. The predicate is invoked by gallery-dl for every
   page URL; on first call per `(manga, chapter)` it answers from disk
   (`chapter_already_packed(output_dir, manga, chapter)`), then memoises.
2. **Simulation pass** (`asyncio.to_thread(gallery.extract_manifest, ...)`).
   Returns `Manifest(paths, series_name)`. The manifest is saved to
   `download_files` (and `files_expected` / `chapters_total` are set).
   `series_name` updates the target's `name`.
3. If cancel was requested between extract and the real run, mark cancelled
   and return.
4. **Real download** (`asyncio.to_thread(gallery.run_download, ...)`):
   - `service.mark_running(...)` → status flips to `running`.
   - `live_progress.start(job.id)`.
   - Run gallery-dl with a callback that records each completed relpath and
     raises `StopExtraction` if the cancel flag is set.
   - On return, count files actually on disk (`count_present`).
   - Persist via `finish_job` (status = `completed`/`failed` from exit code)
     or `mark_cancelled`.
   - `live_progress.clear(job.id)`.
5. If `records` carry a `manga` field, refine `targets.name` from it (the
   real pass has better metadata than the simulation).
6. If `exit_code == 0` and not cancelled, run `_run_postprocess(...)`:
   - Look up `postprocess_root` and `output_dir` from app_config / the job.
   - Re-validate the output dir is under the root.
   - `postprocess.run(...)` — see [§4.7 Postprocessing].
   - Persist `postprocess_status`, `postprocess_chapters_packed`,
     `postprocess_error`.

On any exception during 1–4, `_handle_failure(...)` logs, counts whatever
landed on disk, and persists `mark_failed(error=repr(exc))`.

**Cancellation contract:** `request_cancel(id)` is a no-op unless `id ==
self._current_id`. It sets `_cancel_requested = True`. The worker thread
reads that bool inside the per-file callback; setting a bool from one
coroutine and reading it from one thread is GIL-atomic and is the only
synchronisation the worker needs (single-writer / single-reader). For a
*pending* (not-yet-started) job, the route also flips the row to `cancelled`
directly via `cancel_pending`.

### 4.6 gallery-dl integration

`downloads/gallery.py`

`Gallery` is a thin façade around three gallery-dl entry points:

- `extractor.find(url)` → `Gallery.find_extractor(url)`. Returns the
  `category` string (e.g. `"mangadex"`) or `None`.
- `SimulationJob` → `Gallery.extract_manifest(url, skip_chapter)`. We don't
  use it raw — we subclass it.
- `DownloadJob` → `Gallery.run_download(url, on_file_complete, skip_chapter)`.
  Also subclassed.

**Why subclass:**

- `_ManifestSimulationJob.handle_directory` overrides gallery-dl's no-op
  simulation to actually populate `pathfmt.directory`. Without it, recorded
  paths are missing their per-chapter directory prefix and progress
  accounting can't match files to chapters. It also opportunistically
  captures the first `manga` / `series` / `title` value seen in any
  kwdict — that becomes `Manifest.series_name`.
- `_ManifestSimulationJob.handle_url` records `(full_path, manga, chapter)`
  for every would-be file. Used both to build the manifest and to apply the
  `skip_chapter` predicate so manifest entries belonging to already-packed
  chapters are omitted (so progress shows real remaining work, not
  re-counted history).
- `_ProgressDownloadJob.handle_url` does the real download via
  `super().handle_url`, then captures a snapshot of the file's metadata
  (`coerce_record_from_kwdict`) into a `_records` list and fires the
  `on_file_complete` callback. When `skip_chapter` returns true for a URL,
  it calls `handle_skip()` instead, which keeps gallery-dl's `archive`
  accounting consistent without writing the file.

Gallery-dl spawns *child* jobs for nested extractors (e.g. a series page
that links to per-chapter pages). The subclasses use `_inherit_shared_state`
so a child job shares its parent's manifest list / records list / callbacks
— a single top-level `.run()` yields one aggregated result.

`Gallery.__init__` calls `config.set(("extractor",), "base-directory", ...)`
and `..., "archive", ...)`. These are *process-global* in gallery-dl, so
constructing more than one `Gallery` per process overwrites the previous
settings. In tests we use `FakeGallery` instead (`tests/fakes.py`), which
honours the same interface but writes files to disk without calling
gallery-dl.

### 4.7 Postprocessing → CBZ

`downloads/postprocess.py`

Postprocessing groups the worker's `FileRecord` list by parent directory,
collects each into a `ChapterRecord`, and packs each chapter into a Zip
archive with `.cbz` extension and a `ComicInfo.xml` payload.

Naming convention (Komga-friendly):

```
<output_dir>/<Series>/<Series> - cNNN[ - Title].cbz
```

Chapter number formatting:

- Integer < 1000 → zero-padded to 3 digits (`c042`).
- Integer ≥ 1000 → bare integer (`c1000`).
- Fractional → `c042.5` (whole zero-padded if < 1000).
- Non-numeric → sanitised string.

`sanitize(name)` replaces `[\\/:*?"<>|\x00-\x1f]` with `_`, strips trailing
dots/whitespace, falls back to `"_"`.

Collision handling: if the target path exists, append ` (1)`…` (999)` until
free. `chapter_already_packed(output_dir, manga, chapter)` matches the same
stem family for the watched-target skip logic.

Packing flow per chapter (`_pack_chapter_sync`):

1. Create the series directory if missing.
2. Enumerate the chapter directory fresh — gallery-dl may have rewritten an
   extension between `handle_url` and download completion (e.g. `.png` URL
   serving JPEG bytes), so the path captured at record time can be stale.
3. Build `ComicInfo.xml` (`Series`, `Title`, `Number`, `Volume`, `Writer`,
   `Penciller`, `LanguageISO`, `Year/Month/Day`, `PageCount`, `Manga=Yes`).
4. Write `<target>.cbz.part`, then `.replace(target)` for atomicity.
5. If `delete_raw_after_pack` (from `app_config`, default `True`): guard
   that `ch.dir` is under `downloads_dir`, then `shutil.rmtree(ch.dir)`.

`run(...)` aggregates `PostResult(total, succeeded, failed, error_summary)`.
On any per-chapter exception the rest of the chapters still try; the
summary stitches the first 5 failure messages with `; (+N more)`.

### 4.8 Progress accounting

`downloads/progress.py` + `downloads/live_progress.py`

Per-chapter `stage`:

- `downloading` — at least one expected file is still missing.
- `processing` — all files present but the chapter hasn't been packed yet
  (or the whole job's postprocess is mid-flight).
- `completed` — packed (CBZ exists OR chapter dir gone after delete_raw) OR
  the job has settled with postprocess in a terminal state.

The progress route fuses two information sources:

- **Manifest** (`download_files`) — the list of expected relpaths from the
  simulation pass, persisted to SQLite.
- **Live state** — for an in-flight download, `LiveProgress.snapshot(id)`
  returns the in-memory list of relpaths the worker callback has recorded.
  Used in preference to the filesystem scan: avoids stat-storming the disk
  while the download is hot.

For already-settled jobs, `chapter_progress(...)` scans the chapter dirs on
disk. Stem (not full filename) matching is used because the simulation
pass may predict `.jpg` while the real download writes `.png` once the
extractor sees the response headers.

`stem`-level matching means progress only counts a file as "present" if its
name (without extension) appears in both the manifest and the directory —
the simplest invariant that survives extension churn.

---

## 5. Frontend architecture

### 5.1 Stack

- **Vite 8** + **React 19** + **TypeScript** (`tsc -b --noEmit` for
  typecheck-only; Vite bundles).
- **Mantine 9** (`@mantine/core` + `@mantine/notifications`) for everything
  visual.
- **TanStack Query 5** for server state.
- **Biome 2** for lint + format (replaces ESLint + Prettier).
- **Vitest** for unit tests, **Playwright** for e2e.

### 5.2 Generated API client

Everything under `frontend/src/api/` is produced by
`@hey-api/openapi-ts` from the live backend's `/openapi.json`. Two plugins
are configured (`openapi-ts.config.ts`):

- `@hey-api/client-fetch` — the low-level `fetch`-based client.
- `@tanstack/react-query` — produces typed `*Options()` /
  `*Mutation()` builders so components write:

  ```ts
  const { data } = useQuery(listTargetsOptions());
  const create = useMutation({ ...createDownloadMutation(), onSuccess: ... });
  ```

The `client.gen.ts` `setConfig({ baseUrl: "" })` lets requests be relative —
in dev they go through the Vite proxy to `:8000`, in prod they hit the same
origin that's serving the SPA.

After backend route/schema changes, regenerate via `mise run generate:client`
(with the dev server running so `/openapi.json` is reachable). Generated
files are committed.

### 5.3 Top-level structure

`main.tsx` wraps the tree in `<MantineProvider defaultColorScheme="auto">`,
`<Notifications position="top-right" />`, and `<QueryClientProvider>`. The
preceding inline `<script>` in `index.html` reads the persisted color scheme
from `localStorage` and sets `data-mantine-color-scheme` before React mounts
— prevents the FOUC flash.

`App.tsx` is the only routing-ish component (Mantine `<Tabs>`). Three tabs:

- **Library** — `SubmitForm` + `TargetsList`.
- **Jobs** — `ActiveJobCard` (if a job is selected) + `RecentList`.
- **Config** — `ConfigPanel`.

Clicking "open job #X" on a target jumps to the Jobs tab with that download
selected (via `openJob` callback).

### 5.4 Components

| Component             | What it does                                                                                          |
|-----------------------|--------------------------------------------------------------------------------------------------------|
| `SubmitForm`          | URL input + `DirectoryPicker` for output dir; `POST /api/downloads` on submit. Notification on success/error. Seeds the picker with `postprocess_default_output_dir` until the user touches it. |
| `TargetsList`         | Library tab. Polled every `REFETCH_LIST_MS` (2 s). Filters: search, watched/unwatched, status (`active`/`completed`/`failed`/`no-runs`), extractor, sort. Each row has a `Watch` switch, period override input, "Poll now", "Delete", and "open job #N" link. |
| `RecentList`          | Recent downloads. Same polling. Filters: search, status, sort. Rows are clickable to open in `ActiveJobCard`; cancel + requeue inline. |
| `ActiveJobCard`       | Selected job's full view. Polls every `REFETCH_ACTIVE_MS` (1 s) but only while non-terminal. Shows a Mantine `<Stepper>` with the 5-step user-facing job lifecycle ("Scheduled → Fetching metadata → Downloading → Processing → Completed"), plus `ProgressCard`. |
| `ProgressCard`        | Renders the per-chapter list returned by `GET /api/downloads/{id}/progress`. Each chapter has a colored stage badge. Top-level progress bar is `(non-downloading chapters) / (total chapters)`. |
| `ConfigPanel`         | Edits postprocess root, default output dir, delete_raw, default watch period; theme switcher; library export/import. |
| `DirectoryPicker`     | Reusable `Select` + "create folder" inline form. Loads `/api/output-dirs` only when `enabled` (`postprocess_root` is set). Used by both `SubmitForm` and `ConfigPanel`. |
| `HealthBadge`         | Tiny "backend OK / unreachable" pill in the header. Plain `useQuery(getHealthOptions())`. |
| `ListHeader`          | "Title + count + spinner" row shared by Library and Recent. Shows `<visible> of <total>` when filters are active. |
| `ListToolbar`         | Search input + slot for domain-specific filter `Select`s; second slot below for things like the watched-segment control. |

### 5.5 Lib helpers

| File                  | Exports                                                                                                                                   |
|-----------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| `status.ts`           | `Status`, `statusColor`, `isTerminal`, `isActive`, `isCancellable`, the `JOB_STEPS` constant, `jobStep(...)`. Owns the UI-only `CANCELLING_LABEL` (`"cancelling"`) which is *not* a backend status. |
| `polling.ts`          | `REFETCH_ACTIVE_MS = 1000`, `REFETCH_LIST_MS = 2000`.                                                                                     |
| `invalidate.ts`       | `useDataInvalidators()` hook returning `{ downloads, targets, config, outputDirs, download(id) }` — named invalidators reused everywhere. |
| `apiError.ts`         | `extractErrorMessage(err)` — peeks at FastAPI's `detail` shape before falling back to `Error.message`.                                    |
| `optimisticCancel.ts` | `useOptimisticCancel(id, status)` (single job) + `useOptimisticCancelMany(items)` (list). Shows "Cancelling…" between the user clicking Cancel and the server reflecting it. Auto-clears on terminal. |
| `listFilters.ts`      | `makeNeedleMatcher(needle, ...getters)` — case-insensitive substring match over an arbitrary set of field getters.                        |
| `time.ts`             | `formatRel(iso)` → `"3h ago"` etc.                                                                                                        |
| `libraryBackup.ts`    | `exportLibrary()` / `importLibrary(file)` — bypass the generated client because YAML isn't modelled there. Triggers a browser download for export. |

### 5.6 State strategy

There's effectively no global client state. All data is owned by TanStack
Query:

- Lists poll on a fixed interval (2 s) and aren't paginated.
- The active-job view polls on a faster interval (1 s) and self-disables
  once the job is terminal (via `refetchInterval: (q) => isTerminal(...) ?
  false : ...`).
- Mutations call `useDataInvalidators` after success — there's no manual
  `setQueryData` write-through.
- Two pieces of genuinely-UI state escape this rule: the optimistic-cancel
  flag (per-component `useState`) and the selected job id / current tab
  (top-level `useState` in `App.tsx`).

### 5.7 Tests

- **`*.test.ts` / `*.test.tsx`** — vitest unit tests for `lib/` helpers and
  selected components. `src/test/setup.ts` is loaded by `vitest.config.ts`
  for `jest-dom` matchers.
- **`e2e/`** — Playwright specs run against the real frontend wired to a
  `FakeGallery`-backed backend (`backend/tests/e2e_server.py`). Playwright
  itself spawns both servers — see `playwright.config.ts`. Runs on
  `:8765` (backend) / `:5174` (frontend) so it doesn't collide with `mise
  run dev`.

---

## 6. Lifecycles end-to-end

### 6.1 Single download

```
user types URL → SubmitForm.mutate
  → POST /api/downloads { url, output_dir? }
    └── router.create_download
         ├── Gallery.find_extractor → 400 if no match
         ├── validate_under_root + remember_output_dir   (if output_dir set)
         ├── targets_service.upsert(url, extractor, output_dir)
         ├── downloads_service.insert_pending → status=pending
         └── worker.notify()  ◄── wakes Worker._wakeup event

Worker loop wakes
  └── claim_next_pending → status=extracting, started_at=now
       └── _process(job)
            ├── _build_skip_chapter   (watched targets only)
            ├── _extract_manifest   (gallery-dl SimulationJob, asyncio.to_thread)
            │     → save_manifest, set targets.name (if discovered)
            ├── mark_running → status=running
            ├── live.start(id)
            ├── run_download (asyncio.to_thread)
            │     callbacks → live.record(id, relpath)
            │     cancel? → StopExtraction → exits cleanly
            ├── count_present → finish_job(exit_code, present)
            │                   OR mark_cancelled(present)
            ├── live.clear(id)
            └── if exit==0 and not cancelled:
                   _run_postprocess
                     ├── mark_postprocess(running)
                     ├── postprocess.run → CBZs under <output_dir>/<Series>/
                     └── mark_postprocess(completed/failed)
```

While this runs, the UI is polling `GET /api/downloads/{id}` (1 s) and
`GET /api/downloads/{id}/progress` (1 s); both endpoints self-disable in
the client once the row is terminal.

### 6.2 Watched-target re-poll

```
Poller wakes (every 30 s, or .notify())
  └── _tick_once
       ├── load default_watch_period from app_config
       ├── list_watched
       └── for each target:
            ├── is_due(target, default_period, now)?
            ├── has_active_for_target(id)?  ── skip if yes
            ├── downloads_service.insert_pending(url, extractor, output_dir, target_id)
            └── mark_polled
       └── if anything queued: worker.notify()

→ Worker picks it up from `pending`, same flow as a manual submit
→ skip_chapter predicate avoids re-downloading chapters that already
  exist as CBZs under the output dir.
```

### 6.3 Cancel

```
UI clicks Cancel
  → cancelMutation.mark()    ─── (optimistic flag → "Cancelling…")
  → POST /api/downloads/{id}/cancel
    └── router.cancel_download
         ├── 409 if status in TERMINAL_STATUSES
         ├── worker.request_cancel(id)   ── sets bool if it's the current job
         └── service.cancel_pending(id)  ── flips status=cancelled if still pending

If the job was running:
  worker's per-file callback observes _cancel_requested
   └── raises StopExtraction
        └── gallery-dl unwinds, run_download returns
             └── service.mark_cancelled(id, present)
```

### 6.4 Boot recovery

If the process is killed while a download is running, the row stays in
`extracting`/`running` until the next start. `mark_interrupted_on_boot` in
`lifespan` flips every such row to `failed` with
`error = "interrupted: backend restarted"`. Logged as a warning. The user
can `Requeue` from the UI.

---

## 7. API surface (summary)

All routes are mounted under `/api`.

| Method | Path                                | Operation                                                                 |
|--------|-------------------------------------|---------------------------------------------------------------------------|
| GET    | `/health`                           | `getHealth` — `{status: "ok"}`                                            |
| GET    | `/downloads`                        | `listDownloads` — most-recent 50                                          |
| POST   | `/downloads`                        | `createDownload` (url, output_dir?)                                       |
| GET    | `/downloads/{id}`                   | `getDownload`                                                             |
| POST   | `/downloads/{id}/cancel`            | `cancelDownload`                                                          |
| POST   | `/downloads/{id}/requeue`           | `requeueDownload` (terminal → pending)                                    |
| GET    | `/downloads/{id}/progress`          | `getDownloadProgress` (chapter list + stages)                             |
| GET    | `/targets`                          | `listTargets` (with most-recent-download summary)                         |
| GET    | `/targets/{id}`                     | `getTarget`                                                               |
| PATCH  | `/targets/{id}`                     | `updateTarget` (watched, watch_period, output_dir)                        |
| DELETE | `/targets/{id}`                     | `deleteTarget` (409 if active)                                            |
| POST   | `/targets/{id}/poll`                | `pollTarget` (force a re-poll)                                            |
| GET    | `/output-dirs`                      | `listOutputDirs` (direct children of postprocess_root)                    |
| POST   | `/output-dirs`                      | `createOutputDir` (single dir under root)                                 |
| GET    | `/config`                           | `getConfig`                                                               |
| PUT    | `/config`                           | `putConfig` (validates, may clear `postprocess_known_output_dirs`)        |
| GET    | `/library/export`                   | `exportLibrary` — YAML, `application/yaml`                                |
| POST   | `/library/import`                   | `importLibrary` — accepts YAML body, returns `LibraryImportResult`        |

Full request/response shapes are codified in `frontend/src/api/types.gen.ts`
and (server-side) in each domain's `schemas.py`.

---

## 8. Testing

### 8.1 Backend

`pytest`, `pytest-asyncio` (auto mode). Test layout mirrors `src/`:

```
tests/
  conftest.py                  ← TestClient fixture wiring create_app(...) to FakeGallery
  fakes.py                     ← FakeGallery + FakeGalleryConfig
  e2e_server.py                ← ASGI app for Playwright
  test_database.py             ← schema/migration coverage
  test_config.py               ← Settings env parsing
  <domain>/test_router.py      ← full-stack HTTP via TestClient
  <domain>/test_service.py     ← service-layer SQL
  downloads/test_worker.py     ← worker lifecycle, cancellation, postprocess
  downloads/test_postprocess.py
  downloads/test_progress.py / test_live_progress.py
  targets/test_poller.py
  targets/test_utils.py        ← parse_duration / format_duration
```

`FakeGallery` (in `tests/fakes.py`) lets tests configure per-URL manifests,
records, and series names without ever touching gallery-dl. It honours the
`skip_chapter` predicate and the `on_file_complete` / `StopExtraction`
contract so cancellation paths can be exercised.

### 8.2 Frontend

- **Vitest** (`pnpm test` / `mise run test:frontend`) — jsdom + Testing
  Library for components, plain `describe/it` for `lib/` helpers. Setup in
  `src/test/setup.ts`.
- **Playwright** (`pnpm test:e2e`) — boots the real React app against the
  `FakeGallery`-backed backend. Useful smoke for the submit → progress →
  completion path.

---

## 9. Deployment

### 9.1 Local

`mise install && mise run install && mise run dev`. See `README.md` and
`mise.toml`.

### 9.2 Proxmox LXC

`scripts/proxmox-install.sh` does the full lift on a Proxmox VE host:

1. Optionally mount a CIFS share on the host (uid=100000/gid=110000 so the
   unprivileged CT can write through the bind mount), add an fstab entry.
2. Create the CT (Debian 13 template, default unprivileged, `vmbr0`, 64 GB,
   2 cores, 1 GB RAM — all overridable).
3. `pct set <CTID> -mp0 <host_dir>,mp=/mnt/nas` if a NAS was provided.
4. Bootstrap: `apt-get install ffmpeg git ca-certificates curl sudo`,
   create `gallery-dl` system user, install `mise` to `/usr/local/bin`.
5. Push source via `tar | pct exec ... tar -x`.
6. `mise run install:prod` (uv sync `--frozen --no-dev`, pnpm install).
7. `mise run build` (Vite production bundle).
8. Write `/etc/systemd/system/gallery-dl-webui.service`:
   - `ExecStart=/usr/local/bin/mise run -C ${APP_DIR} serve:backend`
   - Sandbox: `ProtectSystem=strict`, `ProtectHome=yes`,
     `NoNewPrivileges=yes`, `PrivateTmp=yes`, `KillMode=mixed`.
   - `ReadWritePaths=${DATA_DIR}` plus an optional `extra-rw-paths.conf`
     drop-in for `EXTRA_RW_PATHS` (e.g. `/mnt/nas/manga`).
9. Enable + start the service. Logs are `journalctl -u gallery-dl-webui`.

`proxmox-update.sh` re-syncs the source (preserving `.venv` /
`node_modules`), reinstalls, rebuilds, and restarts. It also includes a
one-time migration from older `ExecStart=` lines.

`proxmox-uninstall.sh` stops + destroys the CT, with a confirmation prompt
unless `FORCE=1`.

`_proxmox-lib.sh` provides `log/die/in_ct/in_ct_sh/as_app` helpers shared
by the three scripts.

---

## 10. Design decisions worth knowing

- **One worker, one DB connection.** Simplifies everything: no row-level
  locking, no fairness concerns, no concurrent-job tax on the disk. The
  cost is a serialised queue, which has been fine in practice.
- **Sim-then-real.** Running gallery-dl in simulation mode first lets us
  precompute the file manifest (and capture the series name) before we
  decide whether to start writing. The simulation pass is what makes the
  progress UI possible without instrumenting gallery-dl's internals.
- **Manifest stored in SQLite, live progress in memory.** Restart-safe
  history of *what was expected* (so you can re-render a completed job's
  per-chapter breakdown) without paying disk for *real-time* progress, which
  is only meaningful while the worker is alive.
- **Stem-level progress matching.** Filenames-without-extension are the
  invariant that survives gallery-dl's mid-flight extension rewrites.
- **Watched targets via `skip_chapter`.** Re-running an already-fetched
  series doesn't waste bandwidth, but the manifest still says "0 new
  chapters" which the UI shows truthfully.
- **Path validation at every entry.** Every user-supplied path (output dir
  on submit, default output dir in config, output dir on PATCH target,
  paths in YAML import) goes through `validate_under_root` so a misconfig
  surfaces as a 400, never as a half-completed write somewhere outside the
  sandbox.
- **`ProtectSystem=strict` + write-probe.** Saving the config does a real
  `write_bytes(b"")` + `unlink` on the configured paths, so a missing
  `ReadWritePaths=` whitelist throws immediately instead of failing the
  first download.
- **Cancellation via `StopExtraction`.** Hijacking gallery-dl's own
  documented "stop nicely" exception means the dispatcher unwinds cleanly
  and `run_download` still returns an `exit_code`, so accounting stays
  consistent.
- **Boot recovery flips `extracting`/`running` to `failed`.** The
  alternative is "row stuck forever, requires manual SQL" — the lossier
  but consistent path is better.
- **Single source of truth for paths is the database.** Settings only knows
  about the data dir; the postprocess root and default output dir live in
  `app_config` so the UI can change them at runtime without a service
  restart.

---

## 11. Where to look next

- **New backend route or schema change** → add to the relevant domain's
  `router.py` + `schemas.py`, run the backend, `mise run generate:client`.
- **Worker behavior** → `downloads/worker.py` for orchestration,
  `downloads/gallery.py` for gallery-dl integration, `downloads/postprocess.py`
  for CBZ packing.
- **Watched-target scheduling** → `targets/poller.py` + `targets/utils.py`.
- **Path/output validation** → `output_dirs/utils.py`.
- **Frontend UI behavior** → `frontend/src/components/<thing>.tsx`. Most
  components are self-contained; cross-cutting concerns live in
  `frontend/src/lib/`.
- **Deployment** → `scripts/proxmox-*.sh` and `mise.toml`. The systemd unit
  itself is written inline in `proxmox-install.sh`.
