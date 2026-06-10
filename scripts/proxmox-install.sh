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
#
# The Config page in the UI lets you set a "postprocessed output directory" for
# Komga-friendly CBZ output. If that path is outside DATA_DIR, it must appear
# in EXTRA_RW_PATHS — otherwise the systemd sandbox will refuse writes (the UI
# surfaces this as a 400 from a save-time write-probe).
#
# CIFS / NAS share: by default the script asks at install time whether to
# mount a CIFS share from a NAS on the Proxmox host and bind-mount it into
# the CT (at /mnt/nas). Follows
# https://forum.proxmox.com/threads/tutorial-unprivileged-lxcs-mount-cifs-shares.101795/
# To skip the prompt non-interactively, set NAS_SHARE="" explicitly. To
# pre-fill answers, set NAS_SHARE / NAS_USER / NAS_PASS (and optionally
# NAS_MOUNT, NAS_HOST_DIR, NAS_LXC_GID). When configured, NAS_MOUNT is added
# to EXTRA_RW_PATHS automatically and the service user is added to the
# in-CT 'lxc_shares' group.
#
# Host SSH key: the host's private SSH key is copied into the CT's
# /root/.ssh/ so the in-CT `update` command (lxc-update.sh) can pull the repo
# over SSH using the same identity the Proxmox host uses. Auto-detected from
# /root/.ssh/id_{ed25519,rsa,ecdsa}; override with HOST_SSH_KEY=/path/to/key,
# or set HOST_SSH_KEY="" to skip (in-CT updates then fall back to HTTPS).

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

# CIFS / NAS share. NAS_SHARE is left _unset_ (not empty) by default so we
# know whether to prompt interactively. To explicitly skip without a prompt,
# run with NAS_SHARE="" (note: the empty string opts out).
NAS_SHARE="${NAS_SHARE-__PROMPT__}"
NAS_USER="${NAS_USER-}"
NAS_PASS="${NAS_PASS-}"
NAS_MOUNT="${NAS_MOUNT:-/mnt/nas}"
NAS_HOST_DIR="${NAS_HOST_DIR:-/mnt/lxc_shares/${CT_HOSTNAME}}"
NAS_LXC_GID="${NAS_LXC_GID:-10000}"

# Host SSH key: __AUTO__ → detect; "" → skip; <path> → use that file.
# Consumed by install_host_ssh_key (see _proxmox-lib.sh).
HOST_SSH_KEY="${HOST_SSH_KEY-__AUTO__}"

# ---- Helpers --------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_proxmox-lib.sh"

# ---- Preflight ------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "must run as root"
command -v pct   >/dev/null || die "pct not found (run this on a Proxmox VE host)"
command -v pveam >/dev/null || die "pveam not found (run this on a Proxmox VE host)"

if pct status "$CTID" >/dev/null 2>&1; then
    die "CT $CTID already exists — pick a different CTID or destroy it first"
fi

# ---- NAS share prompt -----------------------------------------------------

if [[ "$NAS_SHARE" == "__PROMPT__" ]]; then
    if [[ -t 0 ]]; then
        read -r -p "Mount a CIFS NAS share into the CT at ${NAS_MOUNT}? [y/N] " _ans
        case "${_ans,,}" in
            y|yes)
                read -r -p "  NAS share (e.g. //nas.local/media): " NAS_SHARE
                read -r -p "  SMB username: "                       NAS_USER
                read -r -s -p "  SMB password: "                    NAS_PASS
                echo
                ;;
            *)
                NAS_SHARE=""
                ;;
        esac
    else
        NAS_SHARE=""
    fi
fi

if [[ -n "$NAS_SHARE" ]]; then
    [[ "$NAS_SHARE" == //* ]] || die "NAS_SHARE must look like //host/share (got: $NAS_SHARE)"
    [[ -n "$NAS_USER" ]] || die "NAS_USER must be set when NAS_SHARE is provided"
    [[ -n "$NAS_PASS" ]] || die "NAS_PASS must be set when NAS_SHARE is provided"
fi

# ---- Host: CIFS share -----------------------------------------------------
#
# On unprivileged LXCs, UID/GID 0 inside the CT maps to 100000 on the host.
# We mount the CIFS share on the host as uid=100000 (=root in CT) and
# gid=10000+100000=110000 (=lxc_shares group in CT), then bind-mount the
# host dir into the CT. dir/file_mode 0770 gives r/w/x to root and to the
# in-CT lxc_shares group (which $APP_USER will be added to).

if [[ -n "$NAS_SHARE" ]]; then
    log "preparing CIFS share $NAS_SHARE on Proxmox host"

    if ! command -v mount.cifs >/dev/null 2>&1; then
        log "installing cifs-utils on host"
        apt-get update -q
        apt-get install -y --no-install-recommends cifs-utils
    fi

    mkdir -p "$NAS_HOST_DIR"

    CREDS_FILE="/root/.smbcredentials-${CT_HOSTNAME}"
    ( umask 077 && cat > "$CREDS_FILE" <<EOF
username=${NAS_USER}
password=${NAS_PASS}
EOF
    )
    chmod 0600 "$CREDS_FILE"

    NAS_HOST_GID=$((100000 + NAS_LXC_GID))

    FSTAB_OPTS="_netdev,x-systemd.automount,noatime,uid=100000,gid=${NAS_HOST_GID},dir_mode=0770,file_mode=0770,credentials=${CREDS_FILE}"
    FSTAB_LINE="${NAS_SHARE} ${NAS_HOST_DIR} cifs ${FSTAB_OPTS} 0 0"

    if grep -qE "^[^#].* ${NAS_HOST_DIR} cifs " /etc/fstab; then
        log "fstab already has a cifs entry for $NAS_HOST_DIR — leaving it as-is"
    else
        log "adding fstab entry for $NAS_HOST_DIR"
        printf '\n# CIFS share for LXC %s (added by proxmox-install.sh)\n%s\n' \
            "$CTID" "$FSTAB_LINE" >> /etc/fstab
    fi

    systemctl daemon-reload

    if mountpoint -q "$NAS_HOST_DIR"; then
        log "$NAS_HOST_DIR is already mounted"
    else
        log "mounting $NAS_HOST_DIR (validating credentials)"
        mount "$NAS_HOST_DIR" || die "failed to mount $NAS_SHARE at $NAS_HOST_DIR — check share path/credentials"
    fi

    # Make the in-CT mount path writable by the systemd sandbox.
    if [[ -z "$EXTRA_RW_PATHS" ]]; then
        EXTRA_RW_PATHS="$NAS_MOUNT"
    else
        EXTRA_RW_PATHS="${EXTRA_RW_PATHS}:${NAS_MOUNT}"
    fi
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

if [[ -n "$NAS_SHARE" ]]; then
    log "bind-mounting $NAS_HOST_DIR into CT at $NAS_MOUNT"
    pct set "$CTID" -mp0 "${NAS_HOST_DIR},mp=${NAS_MOUNT}"
fi

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

# Allow the service user to read its own system-unit journal via journalctl
# — required by the in-app Live Log Tail. systemd-journal exists on Debian
# by default; if not, fall back to `adm` (also accepted by journald ACLs).
in_ct_sh "getent group systemd-journal >/dev/null \
    && usermod -aG systemd-journal '${APP_USER}' \
    || usermod -aG adm '${APP_USER}' || true"

if [[ -n "$NAS_SHARE" ]]; then
    log "creating 'lxc_shares' group (GID ${NAS_LXC_GID}) and adding $APP_USER to it"
    in_ct_sh "getent group lxc_shares >/dev/null || groupadd -g ${NAS_LXC_GID} lxc_shares"
    in_ct_sh "usermod -aG lxc_shares '${APP_USER}'"
fi

# Pinned so deploys are reproducible — the installer honours MISE_VERSION.
# Override via env to install a different release.
MISE_VERSION="${MISE_VERSION:-v2026.6.2}"

log "installing mise ${MISE_VERSION} into /usr/local/bin"
in_ct_sh "MISE_VERSION='${MISE_VERSION}' sh -c 'curl -fsSL https://mise.run | sh'"
in_ct_sh "install -m 0755 /root/.local/bin/mise /usr/local/bin/mise"

# ---- Push source into CT --------------------------------------------------

log "copying source into CT at $APP_DIR"
# NOTE: .git/ is intentionally NOT excluded — the in-app update check
# (backend/maintenance/update_check.py) reads .git/HEAD + .git/config to
# compare the installed sha against upstream on GitHub. A shallow clone's
# .git/ is small (~tens of KB).
tar -C "$SRC_DIR" \
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
  | in_ct tar -C "$APP_DIR" -xf -
in_ct chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---- Install toolchain + deps via mise ------------------------------------
#
# `mise run install:prod` installs the pinned toolchain (python/uv/node) on
# demand, then enables pnpm via corepack and runs `uv sync --no-dev` +
# `pnpm install`. The task lives in mise.toml so the same command works
# locally and here.

log "trusting mise config"
as_app mise trust "$APP_DIR/mise.toml"

log "installing toolchain + backend + frontend deps via mise (this may take a few minutes on first run)"
as_app mise run -C "$APP_DIR" install:prod

log "building frontend via mise"
as_app mise run -C "$APP_DIR" build

# ---- Host SSH key for in-CT git over SSH ---------------------------------
#
# Copy the Proxmox host's SSH key into the CT so the in-CT `update` command
# can pull the repo over SSH with the same identity the host uses. Skipped
# silently if no key is found (HOST_SSH_KEY="" or no /root/.ssh/id_*).

install_host_ssh_key

# ---- In-CT updater (/usr/local/bin/update) --------------------------------
#
# Drop the in-CT updater on the PATH so the operator can `pct console <CTID>`
# (root autologin is set up further down) and just type `update`. The script
# clones a fresh checkout — over SSH if install_host_ssh_key seeded the
# host's key, otherwise over HTTPS — re-runs mise install:prod + build, and
# restarts the systemd unit. See scripts/lxc-update.sh.

log "installing /usr/local/bin/update (in-CT updater)"
in_ct install -m 0755 "$APP_DIR/scripts/lxc-update.sh" /usr/local/bin/update

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

ExecStart=/usr/local/bin/mise run -C ${APP_DIR} serve:backend

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

# ---- In-CT update trigger units -------------------------------------------
#
# Two extra units let the sandboxed webapp self-update without sudo/polkit:
#   * gallery-dl-webui-update.path     watches ${DATA_DIR}/.update-request
#   * gallery-dl-webui-update.service  runs /usr/local/bin/update as root
# The webapp drops the trigger file via the Maintenance tab; the path unit
# fires the oneshot service, which ends by restarting gallery-dl-webui.
# ExecStartPre removes the trigger so the next write re-arms it.

log "writing /etc/systemd/system/gallery-dl-webui-update.service"
in_ct bash -c "cat > /etc/systemd/system/gallery-dl-webui-update.service" <<EOF
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

log "writing /etc/systemd/system/gallery-dl-webui-update.path"
in_ct bash -c "cat > /etc/systemd/system/gallery-dl-webui-update.path" <<EOF
[Unit]
Description=Trigger gallery-dl webui updater on request
After=gallery-dl-webui.service

[Path]
PathExists=${DATA_DIR}/.update-request
Unit=gallery-dl-webui-update.service

[Install]
WantedBy=multi-user.target
EOF

in_ct systemctl daemon-reload
in_ct systemctl enable --now gallery-dl-webui-update.path

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
if [[ -n "$NAS_SHARE" ]]; then
    echo
    echo "  NAS:     $NAS_SHARE → ${NAS_HOST_DIR} (host) → ${NAS_MOUNT} (in CT)"
    echo "           creds at /root/.smbcredentials-${CT_HOSTNAME} on the host"
fi
