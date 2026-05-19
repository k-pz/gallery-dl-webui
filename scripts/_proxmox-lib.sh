#!/usr/bin/env bash
# Shared helpers for scripts/proxmox-*.sh — colored log/die output and
# pct-exec wrappers. Source this after CTID / APP_USER / DATA_DIR are set:
#
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/_proxmox-lib.sh"
#
# Functions are evaluated lazily, so the $CTID etc. dependencies only need
# to exist at call time. log/die work without any container context.

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Run a command (or a bash one-liner) inside the LXC identified by $CTID.
in_ct() { pct exec "$CTID" -- "$@"; }
in_ct_sh() { pct exec "$CTID" -- bash -lc "$*"; }

# Run a command in the CT as $APP_USER, with HOME pointed at $DATA_DIR (where
# mise stores its installed tools) and a clean PATH containing /usr/local/bin
# so the system-wide `mise` is found. Used for every mise / uv / pnpm call.
as_app() {
    pct exec "$CTID" -- sudo -u "$APP_USER" -H \
        env PATH=/usr/local/bin:/usr/bin:/bin HOME="$DATA_DIR" \
        "$@"
}
