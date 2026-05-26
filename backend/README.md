# Backend

FastAPI app behind a single-process `gallery-dl` worker queue. SQLite (via
`aiosqlite`) holds the job, target, library, and maintenance state.

See the [top-level README](../README.md) for the full dev workflow and the
environment-variable surface. This file is the backend-specific view.

## Common commands

All run through `mise` from the repo root so the pinned Python (3.14) and
`uv` are picked up automatically:

```sh
mise run dev:backend        # uvicorn :8000 with --reload
mise run lint:backend       # ruff check + ruff format --check
mise run typecheck:backend  # ty check
mise run test:backend       # pytest (with --cov in CI)
mise run fix:backend        # ruff --fix + ruff format
mise run serve:backend      # production: `uv run --no-dev python -m backend`
```

For one-offs, run `uv run …` from this directory — it picks the pinned
Python via the mise shims on `PATH`.

## Module layout

`src/backend/` is structured by domain. Each domain owns its own
`router.py`, Pydantic `schemas.py`, `service.py`, and (where relevant)
background `worker.py` / `live_progress.py`.

| Path                  | Purpose                                                  |
|-----------------------|----------------------------------------------------------|
| `main.py`             | `create_app` factory, lifespan, router + middleware wiring |
| `__main__.py`         | `python -m backend` entrypoint (uvicorn programmatic boot) |
| `config.py`           | `Settings` + `load_settings` (reads `WEBUI_*` env vars)   |
| `database.py`         | aiosqlite connection lifecycle, schema, migrations        |
| `events.py`           | `EventBus` — in-process pub/sub for the websocket fan-out |
| `middleware.py`       | Per-request event collector → `X-Events` response header  |
| `logging_setup.py`    | Logging config (levels, formatters, journald-friendly)    |
| `exceptions.py`       | `BadRequestError` / `ConflictError` / `NotFoundError` etc.|
| `dependencies.py`     | Shared FastAPI deps (db handle, settings)                 |
| `downloads/`          | Download domain: router, worker, gallery-dl integration, postprocess (CBZ + Komga `series.json`), live progress, schemas |
| `targets/`            | Watched targets: poller, durations heuristic, schemas     |
| `maintenance/`        | Maintenance jobs (rebuild_library, Komga push, unwatch ended, regen, LXC update) + worker + live progress + update_check |
| `realtime/`           | WebSocket endpoint that fans `EventBus` events out to clients |
| `logs/`               | Live `journalctl` tail (powers the in-app Logs tab)       |
| `app_config/`         | App-wide config endpoint (root, default output dir, …)    |
| `library/`            | YAML library import/export                                |
| `output_dirs/`        | Output-dir autocomplete + write-probe                     |
| `health/`             | Cheap `/api/health` probe (used by `HEALTHCHECK` + LXC monitor) |

## Tests

`tests/` mirrors the domain layout. `tests/conftest.py` wires up shared
fixtures (temp data dir, in-memory db, fake gallery). `tests/e2e_server.py`
is the entrypoint Playwright drives from `frontend/e2e/`.

```sh
mise run test:backend           # pytest, no coverage
uv run pytest --cov=backend     # local coverage report
uv run pytest tests/downloads   # one domain
uv run pytest -k cancel         # one keyword
```

## Adding an endpoint

1. Add the route to the relevant domain's `router.py` (or create a new
   domain package mirroring `health/`).
2. Add request/response shapes to that domain's `schemas.py`.
3. Wire the router into `main.py:create_app` if it's a new domain.
4. From `frontend/`, run `mise run generate:client` against a live backend
   to refresh the typed TS client in `frontend/src/api/`.
