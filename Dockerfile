# gallery-dl-webui — production image
#
# Two-stage build: stage one runs `pnpm build` to emit `frontend/dist/`,
# stage two assembles the runtime — Python 3.14 + uv-synced backend deps —
# and copies the built frontend in. The final image runs `python -m backend`
# (same entrypoint the systemd unit on the Proxmox LXC uses), which mounts the
# built `frontend/dist/` at `/` so a single container serves both API + SPA.

# ---------- stage 1: build the frontend ----------
FROM node:24.15.0-bookworm-slim AS frontend-build
WORKDIR /app/frontend

# Enable the corepack-pinned pnpm version up front so layers cache cleanly.
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# ---------- stage 2: runtime ----------
FROM python:3.14-slim-bookworm AS runtime

# uv pulls Python deps; ffmpeg/exiftool aren't required for gallery-dl's core
# extractors. Keep the runtime layer lean — the build artifacts (the .venv +
# the built SPA) come from this stage's own COPY blocks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 webui \
    && useradd  --system --uid 1000 --gid webui --create-home --home-dir /home/webui webui

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Backend dependencies first (cached when only sources change). `uv sync --no-dev`
# matches the production install Proxmox uses — same lockfile, same exclusions.
COPY backend/pyproject.toml backend/uv.lock /app/backend/
RUN cd /app/backend \
    && uv sync --frozen --no-dev --no-install-project

# Source last so a code-only change re-uses the dep layer.
COPY backend/ /app/backend/
RUN cd /app/backend && uv sync --frozen --no-dev

# The Python app expects `frontend/dist/` next to the backend (it's resolved
# relative to REPO_ROOT in backend.main). Copy the artefact from stage 1 there.
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

ENV WEBUI_DATA_DIR=/data \
    WEBUI_HOST=0.0.0.0 \
    WEBUI_PORT=8000 \
    PATH="/app/backend/.venv/bin:${PATH}"

RUN mkdir -p /data && chown -R webui:webui /data /app
USER webui

EXPOSE 8000
VOLUME ["/data"]

# Quick liveness probe — the /api/health route is the same one the
# Proxmox LXC's monitoring uses and never touches downloads.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${WEBUI_PORT}/api/health || exit 1

WORKDIR /app/backend
# exec form so SIGTERM lands on python directly (the asyncio lifespan
# stops the worker + closes the db cleanly on a graceful shutdown).
CMD ["python", "-m", "backend"]
