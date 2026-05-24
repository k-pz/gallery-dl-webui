#!/bin/bash
# Install the toolchain pinned in mise.toml (python, node, uv) and project
# deps, then export PATH so subsequent commands in this session resolve to
# the mise-pinned versions instead of the container's system python/node.
#
# Requires the following hosts in the environment's network allowlist:
#   - mise.run                  (install script)
#   - mise-versions.jdx.dev     (precompiled python tarballs)
#   - api.github.com            ("latest" version lookups, attestation checks)
# Plus the usual github.com, pypi.org, files.pythonhosted.org,
# registry.npmjs.org, nodejs.org (already in the default policy).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

if ! command -v mise >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/mise" ]; then
  curl -fsSL https://mise.run | sh
fi

export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:$PATH"

mise trust "$CLAUDE_PROJECT_DIR/mise.toml"
mise install
mise run install

# Persist PATH for the session so subsequent shell commands see the
# mise-pinned python/node/uv and the corepack-installed pnpm shim.
echo "export PATH=\"\$HOME/.local/bin:\$HOME/.local/share/mise/shims:$CLAUDE_PROJECT_DIR/.local/bin:\$PATH\"" \
  >> "$CLAUDE_ENV_FILE"
