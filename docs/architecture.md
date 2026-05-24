# Architecture

A complete map of the codebase: what each piece does, how the pieces fit
together, and the data and control flow that runs underneath the UI.

## What it is

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

## High-level architecture

### Process model

One uvicorn process hosts the FastAPI app. Inside that process:

```
┌──────────────────────────────── uvicorn / asyncio loop ───────────────────────────────┐
│                                                                                       │
│   FastAPI routers ──┐         WebSocket /api/ws ──── browser cache invalidation      │
│   (request handlers)│         ▲                                                       │
│                     ▼         │                                                       │
│              ┌──────────────┐ │   asyncio.Event (wakeup) ┌────────────────┐           │
│              │   Worker     │ │ ◄──────────────────────── │  HTTP handlers │           │
│              │ (downloads)  │ │ ────────────────────────► │ (notify/cancel)│           │
│              └──────┬───────┘ │   request_cancel(id)     └────────────────┘           │
│                     │         │                                                       │
│           publishes to ──► EventBus ──► every websocket subscriber                    │
│                     │         ▲                                                       │
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

- **Strictly serial worker**: `Worker` runs one job at a time. `claim_next_pending`
  is a guarded UPDATE so the worker's pick can't race the request-handler
  `cancel_pending` route. Per-job cancel flags live in a dict keyed by
  download id.
- **Parallel postprocess**: each job's CBZ packing runs through an
  `asyncio.Semaphore` (`max_parallel_postprocess`, default 3) — chapter
  target paths are reserved sequentially before the parallel pack so stems
  don't collide.
- **No background process / Celery / Redis** — the asyncio event loop is the
  only scheduler.
- **One aiosqlite connection**: every domain shares `app.state.db`. With one
  serial worker, the writers (worker, poller, maintenance worker, request
  handlers) all share the loop and the SQL they emit is either
  single-statement or atomic-by-WHERE-clause — no app-level lock is needed.
- **No HTTP-server lifecycle for state**: app state lives on `app.state`
  (`db`, `settings`, `gallery`, `worker`, `poller`, `live_progress`,
  `event_bus`), populated by the FastAPI `lifespan` context manager and torn
  down on shutdown.
- **gallery-dl runs on a worker thread** via `asyncio.to_thread(...)`.
  Cancellation is cooperative: a bool flag the worker reads inside its
  per-file callback raises `gallery_dl.exception.StopExtraction`, which the
  gallery-dl dispatcher catches and unwinds cleanly.
- **Realtime UI**: state changes publish to an in-process `EventBus`
  (`backend/events.py`). A websocket endpoint `/api/ws` fan-outs to every
  connected browser; the React app pushes incoming events into the TanStack
  Query cache so lists refresh without polling. The existing
  `refetchInterval`s remain as a generous fallback when the socket is
  disconnected.

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

See [Deployment](deployment.md) for the install/update mechanics.

## Repository layout

```
gallery-dl-webui/
├── README.md                  ← "how do I run it"
├── docs/                      ← this folder
├── mise.toml                  ← toolchain + tasks (python/uv/node, dev/build/test)
│
├── backend/                   ← FastAPI app (uv project, src-layout)
│   ├── pyproject.toml         ← deps: fastapi, aiosqlite, gallery-dl, pyyaml
│   ├── src/backend/
│   │   ├── main.py            ← FastAPI factory + lifespan + router registration
│   │   ├── __main__.py        ← `python -m backend` entrypoint (uvicorn)
│   │   ├── config.py          ← Settings (data_dir, host, port from env)
│   │   ├── database.py        ← aiosqlite lifecycle + schema + migrations
│   │   ├── dependencies.py    ← cross-domain FastAPI deps (db, settings, event_bus)
│   │   ├── events.py          ← in-process pub/sub (EventBus + helpers)
│   │   ├── realtime/          ← websocket router that fan-outs EventBus to clients
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
│   │   │   ├── schemas.py / dependencies.py / exceptions.py / constants.py
│   │   │
│   │   ├── targets/           ← saved series; watched/poller logic
│   │   │   ├── router.py / service.py / poller.py / utils.py
│   │   │   ├── schemas.py / dependencies.py / exceptions.py
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
See [Backend](backend.md) for the per-domain breakdown.
