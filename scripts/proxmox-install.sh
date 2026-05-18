#!/usr/bin/env bash
# Install gallery-dl-webui as an unprivileged Debian 13 LXC on a Proxmox node.
#
# Usage (run on the Proxmox host as root):
#   bash scripts/proxmox-install.sh
#
# All settings below are overridable via environment variables, e.g.:
#   CTID=200 DISK_GB=32 RAM_MB=2048 bash scripts/proxmox-install.sh
#
# If the repo isn't reachable over SSH from the Proxmox host, point LOCAL_SRC
# at a working tree on the host instead:
#   LOCAL_SRC=/root/gallery-dl-webui bash scripts/proxmox-install.sh
#
# To let the service write outside DATA_DIR (e.g. a NAS bind-mount), pass a
# colon-separated list of paths via EXTRA_RW_PATHS. These are added to the
# systemd sandbox's ReadWritePaths via a drop-in. The bind mount itself must
# already be configured on the host (`pct set <CTID> -mp0 /host/path,mp=/ct/path`):
#   EXTRA_RW_PATHS=/mnt/nas/manga bash scripts/proxmox-install.sh
#   EXTRA_RW_PATHS=/mnt/nas/manga:/mnt/nas/comics bash scripts/proxmox-install.sh

set -euo pipefail

# ---- Config ---------------------------------------------------------------

CTID="${CTID:-110}"
CT_HOSTNAME="${CT_HOSTNAME:-gallery-dl-webui}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
DISK_GB="${DISK_GB:-64}"
RAM_MB="${RAM_MB:-1024}"
SWAP_MB="${SWAP_MB:-512}"
CORES="${CORES:-2}"
BRIDGE="${BRIDGE:-vmbr0}"
UNPRIVILEGED="${UNPRIVILEGED:-1}"

REPO_URL="${REPO_URL:-git@github.com:k-pz/gallery-dl-webui.git}"
REPO_REF="${REPO_REF:-main}"
LOCAL_SRC="${LOCAL_SRC:-}"

APP_USER="${APP_USER:-gallery-dl}"
APP_DIR="${APP_DIR:-/opt/gallery-dl-webui}"
DATA_DIR="${DATA_DIR:-/var/lib/gallery-dl-webui}"
WEBUI_PORT="${WEBUI_PORT:-8000}"

# Colon-separated list of additional paths the service should be allowed to
# write to (added to systemd's ReadWritePaths via a drop-in).
EXTRA_RW_PATHS="${EXTRA_RW_PATHS:-}"

# ---- Helpers --------------------------------------------------------------

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

in_ct() { pct exec "$CTID" -- "$@"; }
in_ct_sh() { pct exec "$CTID" -- bash -lc "$*"; }

# ---- Preflight ------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "must run as root"
command -v pct   >/dev/null || die "pct not found (run this on a Proxmox VE host)"
command -v pveam >/dev/null || die "pveam not found (run this on a Proxmox VE host)"

if pct status "$CTID" >/dev/null 2>&1; then
    die "CT $CTID already exists — pick a different CTID or destroy it first"
fi

# ---- Template -------------------------------------------------------------

log "ensuring Debian 13 template is present in storage '$TEMPLATE_STORAGE'"
pveam update >/dev/null

TEMPLATE_NAME="$(pveam available --section system \
    | awk '/debian-13-standard_.*amd64\.tar\.zst/ {print $2}' \
    | sort -V | tail -1)"
[[ -n "$TEMPLATE_NAME" ]] || die "no debian-13-standard template available from pveam"

TEMPLATE_REF="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE_NAME}"

if ! pveam list "$TEMPLATE_STORAGE" | awk '{print $1}' | grep -qx "$TEMPLATE_REF"; then
    log "downloading $TEMPLATE_NAME → $TEMPLATE_STORAGE"
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE_NAME"
fi

# ---- Source on host (so we can tar-pipe it into the CT) -------------------

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

# ---- Create CT ------------------------------------------------------------

log "creating CT $CTID ($CT_HOSTNAME) on $STORAGE"
pct create "$CTID" "$TEMPLATE_REF" \
    --hostname     "$CT_HOSTNAME" \
    --cores        "$CORES" \
    --memory       "$RAM_MB" \
    --swap         "$SWAP_MB" \
    --rootfs       "${STORAGE}:${DISK_GB}" \
    --net0         "name=eth0,bridge=${BRIDGE},ip=dhcp" \
    --unprivileged "$UNPRIVILEGED" \
    --onboot       1 \
    --features     nesting=1 \
    --ostype       debian

log "starting CT $CTID"
pct start "$CTID"

log "waiting for network in CT"
for _ in $(seq 1 30); do
    if in_ct getent hosts deb.debian.org >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
in_ct getent hosts deb.debian.org >/dev/null \
    || die "CT $CTID has no DNS/network after 30s"

# ---- Bootstrap inside CT --------------------------------------------------

log "installing packages"
in_ct_sh "export DEBIAN_FRONTEND=noninteractive && \
    apt-get update -q && \
    apt-get install -y --no-install-recommends \
        ffmpeg git ca-certificates curl sudo"

log "creating system user '$APP_USER' and dirs"
in_ct_sh "id -u '$APP_USER' >/dev/null 2>&1 || \
    useradd --system --home-dir '$DATA_DIR' --create-home --shell /usr/sbin/nologin '$APP_USER'"
in_ct_sh "mkdir -p '$APP_DIR' '$DATA_DIR/downloads' && \
    chown -R '$APP_USER:$APP_USER' '$APP_DIR' '$DATA_DIR'"

log "installing mise into /usr/local/bin"
in_ct_sh "curl -fsSL https://mise.run | sh"
in_ct_sh "install -m 0755 /root/.local/bin/mise /usr/local/bin/mise"

# ---- Push source into CT --------------------------------------------------

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

# ---- Install pinned toolchain via mise ------------------------------------

log "installing pinned toolchain (python, uv, node, pnpm) via mise as $APP_USER"
in_ct_sh "sudo -u '$APP_USER' -H \
    env PATH=/usr/local/bin:/usr/bin:/bin HOME='$DATA_DIR' \
    mise trust '$APP_DIR/mise.toml'"
in_ct_sh "sudo -u '$APP_USER' -H \
    env PATH=/usr/local/bin:/usr/bin:/bin HOME='$DATA_DIR' \
    mise install -C '$APP_DIR'"

# ---- Backend: uv sync -----------------------------------------------------

log "running uv sync --frozen --no-dev in $APP_DIR/backend as $APP_USER"
in_ct_sh "cd '$APP_DIR/backend' && sudo -u '$APP_USER' -H \
    env PATH=/usr/local/bin:/usr/bin:/bin HOME='$DATA_DIR' \
    mise exec -- uv sync --frozen --no-dev"

# ---- Frontend: pnpm build -------------------------------------------------

log "building frontend in $APP_DIR/frontend as $APP_USER"
in_ct_sh "cd '$APP_DIR/frontend' && sudo -u '$APP_USER' -H \
    env PATH=/usr/local/bin:/usr/bin:/bin HOME='$DATA_DIR' \
    mise exec -- bash -c 'mkdir -p \"\$HOME/.local/bin\" && \
        corepack enable --install-directory=\"\$HOME/.local/bin\" && \
        export PATH=\"\$HOME/.local/bin:\$PATH\" && \
        pnpm install --frozen-lockfile && \
        pnpm build'"

# ---- systemd unit ---------------------------------------------------------

log "writing /etc/systemd/system/gallery-dl-webui.service"
in_ct bash -c "cat > /etc/systemd/system/gallery-dl-webui.service" <<EOF
[Unit]
Description=gallery-dl webui
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend

Environment=WEBUI_DATA_DIR=${DATA_DIR}
Environment=WEBUI_HOST=0.0.0.0
Environment=WEBUI_PORT=${WEBUI_PORT}

ExecStart=/usr/local/bin/mise exec -- uv run --frozen --no-dev python -m backend

Restart=on-failure
RestartSec=5

KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=20

ReadWritePaths=${DATA_DIR}
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

if [[ -n "$EXTRA_RW_PATHS" ]]; then
    log "writing extra ReadWritePaths drop-in: $EXTRA_RW_PATHS"
    in_ct mkdir -p /etc/systemd/system/gallery-dl-webui.service.d
    {
        echo "[Service]"
        IFS=':' read -ra _paths <<< "$EXTRA_RW_PATHS"
        for p in "${_paths[@]}"; do
            [[ -n "$p" ]] && printf 'ReadWritePaths=%s\n' "$p"
        done
    } | in_ct bash -c "cat > /etc/systemd/system/gallery-dl-webui.service.d/extra-rw-paths.conf"
fi

in_ct systemctl daemon-reload
in_ct systemctl enable --now gallery-dl-webui

# ---- Console autologin ----------------------------------------------------

log "enabling root autologin on tty1 (pct console)"
in_ct mkdir -p /etc/systemd/system/container-getty@1.service.d
in_ct bash -c "cat > /etc/systemd/system/container-getty@1.service.d/autologin.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear --keep-baud tty%I 115200,38400,9600 $TERM
EOF
in_ct systemctl daemon-reload
in_ct systemctl restart container-getty@1.service

# ---- Summary --------------------------------------------------------------

CT_IP="$(in_ct hostname -I | awk '{print $1}')"
log "done"
echo
echo "  CT $CTID ($CT_HOSTNAME) is running"
echo "  Service: gallery-dl-webui.service"
echo "  URL:     http://${CT_IP}:${WEBUI_PORT}"
echo
echo "  Logs:    pct exec $CTID -- journalctl -u gallery-dl-webui -f"
echo "  Shell:   pct enter $CTID"
