#!/usr/bin/env bash
# Update an existing gallery-dl-webui LXC created by proxmox-install.sh.
#
# Usage (run on the Proxmox host as root):
#   CTID=110 bash scripts/proxmox-update.sh
#
# Pulls fresh source (git clone of REPO_URL@REPO_REF, or LOCAL_SRC if set),
# rsyncs it into the CT, re-runs `mise install` + `uv sync --frozen --no-dev`,
# rebuilds the frontend, and restarts the systemd service. The CT's
# `backend/.venv` and `frontend/node_modules` are preserved across runs so the
# tools can update them in place.
#
# Overridable env vars (defaults match proxmox-install.sh):
#   CTID, REPO_URL, REPO_REF, LOCAL_SRC, APP_USER, APP_DIR, DATA_DIR,
#   EXTRA_RW_PATHS
#
# If EXTRA_RW_PATHS is set (colon-separated), the systemd ReadWritePaths
# drop-in is (re)written so the service can write to those paths — e.g.
# a NAS bind-mount:
#   EXTRA_RW_PATHS=/mnt/nas/manga bash scripts/proxmox-update.sh
# If EXTRA_RW_PATHS is left unset, any existing drop-in is preserved.

set -euo pipefail

# ---- Config ---------------------------------------------------------------

CTID="${CTID:-110}"

REPO_URL="${REPO_URL:-git@github.com:k-pz/gallery-dl-webui.git}"
REPO_REF="${REPO_REF:-main}"
LOCAL_SRC="${LOCAL_SRC:-}"

APP_USER="${APP_USER:-gallery-dl}"
APP_DIR="${APP_DIR:-/opt/gallery-dl-webui}"
DATA_DIR="${DATA_DIR:-/var/lib/gallery-dl-webui}"
SERVICE="${SERVICE:-gallery-dl-webui.service}"

# Colon-separated list of additional paths the service should be allowed to
# write to. Leave unset to preserve whatever drop-in is already in place.
EXTRA_RW_PATHS="${EXTRA_RW_PATHS:-}"

# ---- Helpers --------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_proxmox-lib.sh"

# ---- Preflight ------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "must run as root"
command -v pct >/dev/null || die "pct not found (run this on a Proxmox VE host)"

pct status "$CTID" >/dev/null 2>&1 \
    || die "CT $CTID does not exist — run proxmox-install.sh first"

if ! pct status "$CTID" | grep -q running; then
    die "CT $CTID is not running — start it with: pct start $CTID"
fi

in_ct test -d "$APP_DIR" \
    || die "$APP_DIR not found in CT $CTID — is this the right container?"

in_ct test -x /usr/local/bin/mise \
    || die "/usr/local/bin/mise not found in CT $CTID — was this CT created by proxmox-install.sh?"

# ---- Source on host -------------------------------------------------------

CLEANUP_SRC=""
if [[ -n "$LOCAL_SRC" ]]; then
    [[ -d "$LOCAL_SRC" ]] || die "LOCAL_SRC=$LOCAL_SRC is not a directory"
    SRC_DIR="$LOCAL_SRC"
    log "using local source: $SRC_DIR"
else
    SRC_DIR="$(mktemp -d -t gallery-dl-webui.XXXXXX)"
    CLEANUP_SRC="$SRC_DIR"
    log "cloning $REPO_URL ($REPO_REF) to $SRC_DIR"
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$SRC_DIR"
fi

cleanup() { [[ -n "$CLEANUP_SRC" ]] && rm -rf "$CLEANUP_SRC"; }
trap cleanup EXIT

# ---- Sync source into CT --------------------------------------------------
#
# Wipe stale files in APP_DIR so deletions upstream don't linger, but keep
# backend/.venv and frontend/node_modules so uv and pnpm can update them in
# place instead of resolving everything from scratch.

log "clearing $APP_DIR (preserving backend/.venv, frontend/node_modules) in CT $CTID"
in_ct_sh "
set -e
cd '$APP_DIR'
find . -mindepth 1 -maxdepth 1 ! -name backend ! -name frontend -exec rm -rf {} +
[ -d backend ]  && find backend  -mindepth 1 -maxdepth 1 ! -name .venv        -exec rm -rf {} +
[ -d frontend ] && find frontend -mindepth 1 -maxdepth 1 ! -name node_modules -exec rm -rf {} +
"

log "copying source into CT at $APP_DIR"
tar -C "$SRC_DIR" \
    --exclude='./.venv' \
    --exclude='./.git' \
    --exclude='./.pytest_cache' \
    --exclude='./.ruff_cache' \
    --exclude='./node_modules' \
    --exclude='./**/node_modules' \
    --exclude='./**/dist' \
    --exclude='./__pycache__' \
    --exclude='./**/__pycache__' \
    --exclude='./.local' \
    --exclude='./.claude' \
    -cf - . \
  | in_ct tar -C "$APP_DIR" -xf -
in_ct chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---- Refresh toolchain + deps via mise ------------------------------------
#
# `mise run install:prod` re-syncs the pinned toolchain (cheap if mise.toml
# hasn't changed), corepack-enables pnpm, and runs uv/pnpm install. Same task
# as proxmox-install.sh — see mise.toml for the definition.

log "trusting mise config"
as_app mise trust "$APP_DIR/mise.toml"

log "refreshing toolchain + backend + frontend deps via mise"
as_app mise run -C "$APP_DIR" install:prod

log "rebuilding frontend via mise"
as_app mise run -C "$APP_DIR" build

# ---- Refresh in-CT updater (/usr/local/bin/update) ------------------------
#
# Older CTs may not have /usr/local/bin/update yet; newer ones may have an
# outdated copy. Refresh unconditionally so the in-CT `update` command always
# matches the script in this checkout.

log "refreshing /usr/local/bin/update (in-CT updater)"
in_ct install -m 0755 "$APP_DIR/scripts/lxc-update.sh" /usr/local/bin/update

# ---- Migrate systemd unit ExecStart (one-time) ----------------------------
#
# Older installs wrote a different ExecStart line — either pre-mise-tasks
# (`/usr/local/bin/mise exec -- uv run --frozen --no-dev python -m backend`)
# or the now-renamed `backend:run` task. The current task is `serve:backend`.
# Swap the line in-place so existing CTs converge — leaves every other
# directive (Environment=, ReadWritePaths=, etc.) untouched.

DESIRED_EXEC="ExecStart=/usr/local/bin/mise run -C ${APP_DIR} serve:backend"
UNIT_PATH="/etc/systemd/system/${SERVICE}"
if ! in_ct grep -qF "$DESIRED_EXEC" "$UNIT_PATH"; then
    log "migrating ${SERVICE} ExecStart to use the mise serve:backend task"
    in_ct sed -i "s|^ExecStart=.*|${DESIRED_EXEC}|" "$UNIT_PATH"
    in_ct systemctl daemon-reload
fi

# ---- Restart --------------------------------------------------------------
#
# `systemctl restart` blocks until both stop and start complete (default 90s
# stop timeout). If a job is in-flight or the asyncio shutdown stalls, the
# script appears to hang. We use --no-block so we can poll for active state
# with our own deadline.

if [[ -n "$EXTRA_RW_PATHS" ]]; then
    log "writing extra ReadWritePaths drop-in: $EXTRA_RW_PATHS"
    in_ct mkdir -p "/etc/systemd/system/${SERVICE}.d"
    {
        echo "[Service]"
        IFS=':' read -ra _paths <<< "$EXTRA_RW_PATHS"
        for p in "${_paths[@]}"; do
            [[ -n "$p" ]] && printf 'ReadWritePaths=%s\n' "$p"
        done
    } | in_ct bash -c "cat > /etc/systemd/system/${SERVICE}.d/extra-rw-paths.conf"
    in_ct systemctl daemon-reload
fi

log "restarting $SERVICE (non-blocking)"
in_ct systemctl restart --no-block "$SERVICE"

log "waiting up to 30s for $SERVICE to be active"
for _ in $(seq 1 30); do
    if in_ct systemctl is-active --quiet "$SERVICE"; then
        break
    fi
    sleep 1
done
in_ct systemctl is-active --quiet "$SERVICE" \
    || die "$SERVICE failed to come back up — check: pct exec $CTID -- journalctl -u $SERVICE -n 50"

CT_IP="$(in_ct hostname -I | awk '{print $1}')"
log "done"
echo
echo "  CT $CTID updated"
echo "  Service: $SERVICE (active)"
echo "  Logs:    pct exec $CTID -- journalctl -u $SERVICE -f"
[[ -n "$CT_IP" ]] && echo "  URL:     http://${CT_IP}:8000"
