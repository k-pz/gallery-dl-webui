#!/usr/bin/env bash
# Update an existing gallery-dl-webui LXC created by proxmox-install.sh.
#
# Usage (run on the Proxmox host as root):
#   CTID=110 bash scripts/proxmox-update.sh
#
# This is a thin host-side driver: it refreshes the in-CT updater
# (/usr/local/bin/update, i.e. scripts/lxc-update.sh) and runs it inside the
# CT, which does the actual work — clone, wipe+sync into APP_DIR, `mise run
# install:prod`, frontend build, systemd unit migrations, service restart.
# Keeping a single implementation means host-driven and in-CT updates can't
# drift apart (they used to mirror ~200 lines of each other).
#
# Host-only concerns handled here: pushing the host's SSH key into the CT and
# (re)writing the ReadWritePaths drop-in. With LOCAL_SRC set, the host tree is
# staged into the CT and the updater installs from it instead of cloning.
#
# Overridable env vars (defaults match proxmox-install.sh):
#   CTID, REPO_URL, REPO_REF, LOCAL_SRC, APP_USER, APP_DIR, DATA_DIR,
#   EXTRA_RW_PATHS, HOST_SSH_KEY
#
# REPO_URL: when unset, the in-CT updater picks SSH if a key was pushed into
# the CT, falling back to HTTPS — set it only to point somewhere unusual.
# REPO_REF is always passed explicitly (default: main) so a host-driven run
# never consumes the webapp's one-shot .update-ref preview sidecar.
#
# If EXTRA_RW_PATHS is set (colon-separated), the systemd ReadWritePaths
# drop-in is (re)written so the service can write to those paths — e.g.
# a NAS bind-mount:
#   EXTRA_RW_PATHS=/mnt/nas/manga bash scripts/proxmox-update.sh
# If EXTRA_RW_PATHS is left unset, any existing drop-in is preserved.
#
# HOST_SSH_KEY: path to a private SSH key on the Proxmox host to install
# into the CT (so the in-CT `update` command can pull over SSH using the
# host's identity). Auto-detected from /root/.ssh/id_{ed25519,rsa,ecdsa};
# set HOST_SSH_KEY="" to skip pushing a key on this run.

set -euo pipefail

# ---- Config ---------------------------------------------------------------

CTID="${CTID:-110}"

REPO_URL="${REPO_URL:-}"
REPO_REF="${REPO_REF:-main}"
LOCAL_SRC="${LOCAL_SRC:-}"

APP_USER="${APP_USER:-gallery-dl}"
APP_DIR="${APP_DIR:-/opt/gallery-dl-webui}"
DATA_DIR="${DATA_DIR:-/var/lib/gallery-dl-webui}"
SERVICE="${SERVICE:-gallery-dl-webui.service}"

# Colon-separated list of additional paths the service should be allowed to
# write to. Leave unset to preserve whatever drop-in is already in place.
EXTRA_RW_PATHS="${EXTRA_RW_PATHS:-}"

# Host SSH key: __AUTO__ → detect; "" → skip; <path> → use that file.
# Consumed by install_host_ssh_key (see _proxmox-lib.sh).
HOST_SSH_KEY="${HOST_SSH_KEY-__AUTO__}"

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

# ---- Refresh host SSH key in CT -------------------------------------------
#
# Re-push the host's SSH key into the CT's /root/.ssh/ on every update so the
# in-CT `update` command keeps working after key rotation. No-op if
# HOST_SSH_KEY="" or no host key is found.

install_host_ssh_key

# ---- Extra ReadWritePaths drop-in (host-only) ------------------------------
#
# Written before the updater runs so the service restart at its end picks the
# drop-in up in the same pass.

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

# ---- Refresh the in-CT updater, then run it --------------------------------
#
# Push this checkout's lxc-update.sh (or LOCAL_SRC's, when deploying a local
# tree) so the run below always uses the script matching the invocation. When
# cloning, the updater re-installs itself from the fresh clone at the end, so
# the CT converges on the deployed ref's copy either way.

UPDATER_SRC="${LOCAL_SRC:-$SCRIPT_DIR/..}/scripts/lxc-update.sh"
[[ -f "$UPDATER_SRC" ]] || die "$UPDATER_SRC not found"
log "refreshing /usr/local/bin/update (in-CT updater) from $UPDATER_SRC"
pct push "$CTID" "$UPDATER_SRC" /usr/local/bin/update \
    --perms 0755 --user root --group root

# Forward the host-side overrides so both halves agree on users/paths.
UPDATE_ENV=(
    "APP_USER=$APP_USER"
    "APP_DIR=$APP_DIR"
    "DATA_DIR=$DATA_DIR"
    "SERVICE=$SERVICE"
)

CT_SRC=""
cleanup() { [[ -n "$CT_SRC" ]] && in_ct rm -rf "$CT_SRC"; }
trap cleanup EXIT

if [[ -n "$LOCAL_SRC" ]]; then
    [[ -d "$LOCAL_SRC" ]] || die "LOCAL_SRC=$LOCAL_SRC is not a directory"
    CT_SRC="$(in_ct mktemp -d -t gallery-dl-webui.XXXXXX)"
    log "staging local source $LOCAL_SRC into CT at $CT_SRC"
    # NOTE: .git/ is intentionally NOT excluded — the in-app update check
    # (backend/maintenance/update_check.py) reads .git/HEAD + .git/config to
    # compare the installed sha against upstream on GitHub.
    tar -C "$LOCAL_SRC" \
        --exclude='./.venv' \
        --exclude='./**/.venv' \
        --exclude='./.pytest_cache' \
        --exclude='./.ruff_cache' \
        --exclude='./node_modules' \
        --exclude='./**/node_modules' \
        --exclude='./**/dist' \
        --exclude='./__pycache__' \
        --exclude='./**/__pycache__' \
        --exclude='./data' \
        --exclude='./data-e2e' \
        --exclude='./.local' \
        --exclude='./.claude' \
        -cf - . \
      | in_ct tar -C "$CT_SRC" -xf -
    UPDATE_ENV+=("SRC_DIR=$CT_SRC")
else
    UPDATE_ENV+=("REPO_REF=$REPO_REF")
    [[ -n "$REPO_URL" ]] && UPDATE_ENV+=("REPO_URL=$REPO_URL")
fi

log "running the in-CT updater"
in_ct env "${UPDATE_ENV[@]}" /usr/local/bin/update

log "done"
echo
echo "  CT $CTID updated"
echo "  Logs: pct exec $CTID -- journalctl -u $SERVICE -f"
