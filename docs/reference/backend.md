---
title: Backend modules
---

# Backend modules

The Python backend is a single FastAPI app organised into per-domain modules
under `backend/src/backend/`. Each module owns its router, Pydantic schemas,
service-layer functions, and any background tasks (worker, poller).

Pages in this section are generated directly from the source code via
[mkdocstrings](https://mkdocstrings.github.io/). Symbols starting with `_`
are filtered out — see `mkdocs.yml` for the full handler config.

## Entry point

::: backend.main
    options:
      show_submodules: false
      members:
        - create_app
        - GalleryFactory
        - SettingsFactory

## Settings

See [Configuration](backend/config.md).

## Domains

| Domain | Page |
|---|---|
| Downloads queue + worker + postprocess | [downloads](backend/downloads.md) |
| Watched targets + poller | [targets](backend/targets.md) |
| Library YAML import/export | [library](backend/library.md) |
| App-wide config endpoint | [app_config](backend/app_config.md) |
| Output-dir picker | [output_dirs](backend/output_dirs.md) |
| Health check | [health](backend/health.md) |

## Shared

::: backend.dependencies

::: backend.exceptions
