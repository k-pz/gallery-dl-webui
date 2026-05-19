#!/usr/bin/env bash
# Build the docs site into ./site.
#
# Steps:
#   1. Dump the FastAPI app's OpenAPI schema to docs/reference/openapi.json so
#      the Redoc embed has something to render.
#   2. Run `mkdocs build --strict` from the repo root.
#
# The backend's `docs` dependency group must be installed:
#   cd backend && uv sync --group docs
#
# Re-runs are idempotent — the dumped openapi.json is gitignored.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Dumping OpenAPI schema"
(cd backend && uv run --group docs python "$REPO_ROOT/scripts/dump-openapi.py" \
    "$REPO_ROOT/docs/reference/openapi.json")

echo "==> Building mkdocs site"
(cd backend && uv run --group docs mkdocs build \
    --config-file "$REPO_ROOT/mkdocs.yml" \
    --strict)

echo "==> Done. Site written to: $REPO_ROOT/site"
