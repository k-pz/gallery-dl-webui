#!/usr/bin/env bash
# Destroy the gallery-dl-webui LXC created by proxmox-install.sh.
#
# Usage (run on the Proxmox host as root):
#   CTID=110 bash scripts/proxmox-uninstall.sh
#
# Prompts for confirmation by default. Set FORCE=1 to skip the prompt:
#   CTID=110 FORCE=1 bash scripts/proxmox-uninstall.sh
#
# This wipes the entire container, including DATA_DIR (downloads + sqlite db)
# and the systemd units the install script wrote inside the CT.
#
# Intentionally NOT touched:
#   - the Debian LXC template in TEMPLATE_STORAGE (other CTs may use it)
#   - host directories referenced by `pct set <CTID> -mp0 ...` bind-mounts
#     (the mount entry in the CT config goes with the CT; the host path stays)
#   - backup archives in any vzdump storage (only references are purged)

set -euo pipefail

# ---- Config ---------------------------------------------------------------

CTID="${CTID:-110}"
FORCE="${FORCE:-0}"

# ---- Helpers --------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_proxmox-lib.sh"

# ---- Preflight ------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "must run as root"
command -v pct >/dev/null || die "pct not found (run this on a Proxmox VE host)"

if ! pct status "$CTID" >/dev/null 2>&1; then
    log "CT $CTID does not exist — nothing to do"
    exit 0
fi

CT_HOSTNAME="$(pct config "$CTID" 2>/dev/null | awk '/^hostname:/ {print $2}')"

# ---- Confirm --------------------------------------------------------------

if [[ "$FORCE" != "1" ]]; then
    echo
    echo "About to destroy CT $CTID (${CT_HOSTNAME:-unknown hostname})."
    echo "Everything inside the container — including downloaded media and the"
    echo "sqlite database — will be permanently removed."
    echo
    echo "Host bind-mount directories and the Debian template are preserved."
    echo
    read -r -p "Continue? [y/N] " reply
    case "$reply" in
        y|Y|yes|YES) ;;
        *) die "aborted" ;;
    esac
fi

# ---- Stop + destroy -------------------------------------------------------

if pct status "$CTID" | grep -q running; then
    log "stopping CT $CTID"
    pct stop "$CTID"
fi

log "destroying CT $CTID"
pct destroy "$CTID" --purge

log "done"
