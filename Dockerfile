# gallery-dl-webui — production image
#
# Two stages: (1) build the frontend with pnpm, (2) install the backend
# venv with uv and copy the built SPA into place. The final image runs
# `python -m backend`, the same entrypoint the Proxmox LXC systemd unit
# uses. The backend serves /api/* and mounts the built SPA at /, so a
# single container is the whole app.
#
# Toolchain versions come from the repo's `mise.toml` (python = "3.14",
# node = "24.15.0") — keep these base tags aligned with the pins there.

# ---------- stage 1: build the frontend ----------
FROM node:24.15.0-bookworm-slim AS frontend-build

WORKDIR /app/frontend

# corepack picks up the pnpm version pinned in package.json's
# `packageManager` field — keeps CI, local dev, and the image in sync.
RUN corepack enable

# `pnpm-workspace.yaml` carries the `allowBuilds: { esbuild: true }` entry that
# pnpm 11 requires to run esbuild's postinstall (storybook drags esbuild into
# vite's active peer set). Without this file in the build context, `pnpm
# install --frozen-lockfile` exits 1 with ERR_PNPM_IGNORED_BUILDS in CI mode.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# ---------- stage 2: runtime ----------
FROM python:3.14-slim-bookworm AS runtime

# ca-certificates: gallery-dl talks to HTTPS sites.
# curl: HEALTHCHECK + occasionally useful for debugging inside the container.
# tini: small init so PID 1 reaps zombies and forwards signals.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 webui \
    && useradd  --system --uid 1000 --gid webui --create-home --home-dir /home/webui webui

# uv handles backend deps. Pull the binary from the upstream image
# rather than pip-installing it — the layer is tiny and the version
# tracks upstream releases.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install backend deps first so a code-only change re-uses the layer.
COPY backend/pyproject.toml backend/uv.lock /app/backend/
RUN cd /app/backend \
    && uv sync --frozen --no-dev --no-install-project

# Now the source itself. `uv sync --no-install-project` above only
# resolves third-party deps; this second sync (after sources land)
# installs the `backend` package itself.
COPY backend/ /app/backend/
RUN cd /app/backend && uv sync --frozen --no-dev

# main.py resolves the built SPA at REPO_ROOT/frontend/dist where
# REPO_ROOT is parents[3] of backend/src/backend/config.py — that's
# /app/. Drop the artefact from stage 1 there.
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

ENV WEBUI_DATA_DIR=/data \
    WEBUI_HOST=0.0.0.0 \
    WEBUI_PORT=8000 \
    PATH="/app/backend/.venv/bin:${PATH}"

RUN mkdir -p /data && chown -R webui:webui /data /app

USER webui
WORKDIR /app/backend

EXPOSE 8000
VOLUME ["/data"]

# /api/health is cheap and never touches the worker queue — same probe
# the Proxmox LXC's monitoring uses.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${WEBUI_PORT}/api/health" || exit 1

# tini forwards SIGTERM to the python process so the asyncio lifespan
# shuts the worker + db down cleanly on `docker stop`.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "backend"]
