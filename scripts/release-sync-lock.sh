#!/usr/bin/env bash
# commitizen pre_bump_hook (see .cz.toml): runs after cz rewrites the
# version literals but before it creates the bump commit + tag. Re-locking
# here means backend/uv.lock (whose [[package]] backend version block
# tracks pyproject.toml) ships *inside* the tagged bump commit — without
# this, every release tag carried a stale lockfile and `uv sync --locked`
# would fail at any tag.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
(cd backend && uv lock)
git add backend/uv.lock
