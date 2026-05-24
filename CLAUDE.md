# gallery-dl-webui — agent guide

## Toolchain: always go through mise

`mise.toml` is the single source of truth for tool versions (python, node, uv).
A `SessionStart` hook (`.claude/hooks/session-start.sh`) installs the pinned
toolchain and puts mise shims on `PATH`, so a bare `python` / `node` / `uv` in
this repo already resolves to the pinned version.

**Do not** invoke `python`, `python3`, `pip`, `pytest`, `node`, or `npm`
directly with assumed versions or paths — and never hardcode a python version
in a script, Dockerfile, or CI file. If you need to know the pinned version,
read `mise.toml`.

## How to run things

Prefer the repo's mise tasks (defined in `mise.toml`) over ad-hoc commands:

| Goal                  | Command                  |
| --------------------- | ------------------------ |
| Install all deps      | `mise run install`       |
| Backend + frontend dev| `mise run dev`           |
| Lint                  | `mise run lint`          |
| Typecheck             | `mise run typecheck`     |
| Tests                 | `mise run test`          |
| All CI checks         | `mise run check`         |
| Auto-fix lint+format  | `mise run fix`           |

Run `mise tasks` to see the full list; scoped variants exist for each side
(e.g. `lint:backend`, `test:frontend`).

For one-off backend commands, use `uv run …` from `backend/` (it picks up the
pinned python via mise). For one-off frontend commands, use `pnpm …` from
`frontend/` (pnpm version comes from `frontend/package.json`'s
`packageManager` field via corepack).

## Repo layout

- `backend/` — FastAPI app, managed with `uv`. Tests: `pytest`. Lint/format:
  `ruff`. Typecheck: `ty`.
- `frontend/` — Vite + React, managed with `pnpm`. Tests: `vitest`. Lint:
  `biome`. Typecheck: `tsc -b --noEmit`.
- `mise.toml` — toolchain pins + every repo task.
- `docs/`, `mkdocs.yml` — MkDocs Material site; build via `mise run docs:build`.
