#!/usr/bin/env bash
# Update gallery-dl-webui from inside the LXC. Mirrors scripts/proxmox-update.sh
# but runs directly inside the CT (no `pct exec` wrappers).
#
# Usage (run as root inside the CT — proxmox-install.sh sets up tty1 autologin
# so `pct console <CTID>` lands you there directly):
#
#   update                                  # installed at /usr/local/bin/update
#   REPO_REF=some-branch update             # pin a different ref
#
# First-time / pre-install bootstrap (no local copy yet):
#
#   curl -fsSL https://raw.githubusercontent.com/k-pz/gallery-dl-webui/main/scripts/lxc-update.sh \
#       | bash
#
# Overridable env vars (defaults match proxmox-install.sh):
#   REPO_URL, REPO_REF, APP_USER, APP_DIR, DATA_DIR, SERVICE

set -euo pipefail

# ---- Config ---------------------------------------------------------------

# Default REPO_URL: prefer SSH when proxmox-install / proxmox-update has
# seeded /root/.ssh/ with the host's key (look for the common defaults).
# Otherwise fall back to HTTPS so the curl-pipe bootstrap and CTs without a
# key still work.
if [[ -z "${REPO_URL:-}" ]]; then
    REPO_URL="https://github.com/k-pz/gallery-dl-webui.git"
    for _k in /root/.ssh/id_ed25519 /root/.ssh/id_rsa /root/.ssh/id_ecdsa; do
        if [[ -f "$_k" ]]; then
            REPO_URL="git@github.com:k-pz/gallery-dl-webui.git"
            break
        fi
    done
    unset _k
fi

APP_USER="${APP_USER:-gallery-dl}"
APP_DIR="${APP_DIR:-/opt/gallery-dl-webui}"
DATA_DIR="${DATA_DIR:-/var/lib/gallery-dl-webui}"
SERVICE="${SERVICE:-gallery-dl-webui.service}"

# If REPO_REF wasn't pinned via env, consult the webapp's preview-ref
# sidecar — the Maintenance tab's "Track a specific ref" input writes it
# alongside .update-request. The file is one line containing a branch /
# tag / SHA. We consume + remove it so a one-shot preview run doesn't
# silently stick around for the next update; the webapp re-creates it on
# the next scheduled update if the preference is still set.
if [[ -z "${REPO_REF:-}" ]] && [[ -f "$DATA_DIR/.update-ref" ]]; then
    REPO_REF="$(head -n1 "$DATA_DIR/.update-ref" | tr -d '[:space:]')"
    rm -f "$DATA_DIR/.update-ref"
fi
REPO_REF="${REPO_REF:-main}"

# ---- Helpers --------------------------------------------------------------

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Run as $APP_USER with the same env mise expects (PATH containing
# /usr/local/bin, HOME pointed at DATA_DIR where mise stores tools).
as_app() {
    sudo -u "$APP_USER" -H \
        env PATH=/usr/local/bin:/usr/bin:/bin HOME="$DATA_DIR" \
        "$@"
}

# ---- Preflight ------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "must run as root (try: sudo $0)"
[[ -d "$APP_DIR" ]] || die "$APP_DIR not found — is this the right container?"
[[ -x /usr/local/bin/mise ]] \
    || die "/usr/local/bin/mise not found — was this CT created by proxmox-install.sh?"
id -u "$APP_USER" >/dev/null 2>&1 || die "user '$APP_USER' does not exist"
command -v git >/dev/null \
    || die "git not found — install with: apt-get install -y git"

# ---- Fetch source ---------------------------------------------------------

SRC_DIR="$(mktemp -d -t gallery-dl-webui.XXXXXX)"
cleanup() { rm -rf "$SRC_DIR"; }
trap cleanup EXIT

log "cloning $REPO_URL ($REPO_REF) to $SRC_DIR"
git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$SRC_DIR"

NEW_REV="$(git -C "$SRC_DIR" rev-parse --short HEAD)"
NEW_SUBJECT="$(git -C "$SRC_DIR" log -1 --pretty=%s)"

# ---- Wipe + repopulate APP_DIR --------------------------------------------
#
# Same preservation rules as proxmox-update.sh: keep backend/.venv and
# frontend/node_modules so uv/pnpm can update them in place.

log "clearing $APP_DIR (preserving backend/.venv, frontend/node_modules)"
(
    cd "$APP_DIR"
    find . -mindepth 1 -maxdepth 1 ! -name backend ! -name frontend -exec rm -rf {} +
    [ -d backend ]  && find backend  -mindepth 1 -maxdepth 1 ! -name .venv        -exec rm -rf {} + || true
    [ -d frontend ] && find frontend -mindepth 1 -maxdepth 1 ! -name node_modules -exec rm -rf {} + || true
)

log "copying source into $APP_DIR"
# NOTE: .git/ is intentionally NOT excluded — the in-app update check
# (backend/maintenance/update_check.py) reads .git/HEAD + .git/config to
# compare the installed sha against upstream on GitHub. A shallow clone's
# .git/ is small (~tens of KB).
tar -C "$SRC_DIR" \
    --exclude='./.venv' \
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
  | tar -C "$APP_DIR" -xf -
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---- Refresh toolchain + deps via mise ------------------------------------

log "trusting mise config"
as_app mise trust "$APP_DIR/mise.toml"

log "refreshing toolchain + backend + frontend deps via mise"
as_app mise run -C "$APP_DIR" install:prod

log "rebuilding frontend via mise"
as_app mise run -C "$APP_DIR" build

# ---- Refresh /usr/local/bin/update so future runs use the new script ------

NEW_UPDATER="$APP_DIR/scripts/lxc-update.sh"
if [[ -f "$NEW_UPDATER" ]]; then
    install -m 0755 "$NEW_UPDATER" /usr/local/bin/update
fi

# ---- Migrate systemd unit ExecStart (one-time) ----------------------------
#
# Matches the equivalent block in proxmox-update.sh so an in-CT update can
# also pick up the rename from `backend:run` / pre-mise-tasks to
# `serve:backend`.

DESIRED_EXEC="ExecStart=/usr/local/bin/mise run -C ${APP_DIR} serve:backend"
UNIT_PATH="/etc/systemd/system/${SERVICE}"
if [[ -f "$UNIT_PATH" ]] && ! grep -qF "$DESIRED_EXEC" "$UNIT_PATH"; then
    log "migrating ${SERVICE} ExecStart to use the mise serve:backend task"
    sed -i "s|^ExecStart=.*|${DESIRED_EXEC}|" "$UNIT_PATH"
    systemctl daemon-reload
fi

# ---- Install in-CT update trigger units -----------------------------------
#
# Older CTs (pre this feature) don't have the path+service pair that lets the
# webapp's Maintenance tab fire this very script. Drop them in idempotently
# so existing installs converge on the first run from the console.
#
# The `enable --now` below runs UNCONDITIONALLY: `systemctl enable` is a
# no-op when the unit is already enabled, and `--now` also re-starts the
# unit if it's drifted to inactive between updates (boot transient, manual
# stop, etc.). Without this, a path unit that stops once stays stopped —
# webapp-triggered updates then silently write a trigger nobody watches.

UPDATE_UNIT_PATH="/etc/systemd/system/gallery-dl-webui-update.path"
UPDATE_UNIT_SERVICE="/etc/systemd/system/gallery-dl-webui-update.service"

if [[ ! -f "$UPDATE_UNIT_SERVICE" ]] || [[ ! -f "$UPDATE_UNIT_PATH" ]]; then
    log "installing webapp-triggered update units"
    cat > "$UPDATE_UNIT_SERVICE" <<EOF
[Unit]
Description=gallery-dl webui in-place updater
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStartPre=/bin/rm -f ${DATA_DIR}/.update-request
ExecStart=/usr/local/bin/update
StandardOutput=journal
StandardError=journal
TimeoutStartSec=30min
EOF
    cat > "$UPDATE_UNIT_PATH" <<EOF
[Unit]
Description=Trigger gallery-dl webui updater on request
After=gallery-dl-webui.service

[Path]
PathExists=${DATA_DIR}/.update-request
Unit=gallery-dl-webui-update.service

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
fi

systemctl enable --now gallery-dl-webui-update.path

# ---- Ensure service user can read its own journal (one-time) --------------
#
# The in-app Live Log Tail shells out to `journalctl -u ${SERVICE}` as the
# service user. journald grants non-root reads to members of the
# `systemd-journal` group (or `adm` on hosts that use the older ACL).
# `usermod -aG` is idempotent — re-running on already-fixed CTs is a no-op.
# The service restart below picks up the new supplementary group.

if getent group systemd-journal >/dev/null; then
    usermod -aG systemd-journal "$APP_USER"
else
    usermod -aG adm "$APP_USER" || true
fi

# ---- Restart --------------------------------------------------------------

log "restarting $SERVICE (non-blocking)"
systemctl restart --no-block "$SERVICE"

log "waiting up to 30s for $SERVICE to be active"
for _ in $(seq 1 30); do
    if systemctl is-active --quiet "$SERVICE"; then
        break
    fi
    sleep 1
done
systemctl is-active --quiet "$SERVICE" \
    || die "$SERVICE failed to come back up — check: journalctl -u $SERVICE -n 50"

CT_IP="$(hostname -I | awk '{print $1}')"
log "done"
echo
echo "  Updated to ${NEW_REV} — ${NEW_SUBJECT}"
echo "  Service: $SERVICE (active)"
echo "  Logs:    journalctl -u $SERVICE -f"
[[ -n "$CT_IP" ]] && echo "  URL:     http://${CT_IP}:8000"
