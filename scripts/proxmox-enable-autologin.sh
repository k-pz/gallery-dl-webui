#!/usr/bin/env bash
# Enable root autologin on the console of an existing Proxmox LXC.
#
# Usage (run on the Proxmox host as root):
#   CTID=110 bash scripts/proxmox-enable-autologin.sh
#
# After this runs, `pct console <CTID>` (and the web UI console) will drop
# straight into a root shell without prompting for a password.
#
# Overridable env vars:
#   CTID   target container id (default: 110)
#   TTY    tty number to auto-login on (default: 1)
#   USER   user to auto-login as (default: root)

set -euo pipefail

CTID="${CTID:-110}"
TTY="${TTY:-1}"
LOGIN_USER="${USER:-root}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

in_ct() { pct exec "$CTID" -- "$@"; }

[[ $EUID -eq 0 ]] || die "must run as root"
command -v pct >/dev/null || die "pct not found (run this on a Proxmox VE host)"

pct status "$CTID" >/dev/null 2>&1 \
    || die "CT $CTID does not exist"

if ! pct status "$CTID" | grep -q running; then
    die "CT $CTID is not running — start it with: pct start $CTID"
fi

UNIT="container-getty@${TTY}.service"
DROPIN_DIR="/etc/systemd/system/${UNIT}.d"

log "writing ${DROPIN_DIR}/autologin.conf in CT $CTID (user=${LOGIN_USER})"
in_ct mkdir -p "$DROPIN_DIR"
# Single-quoted heredoc so %I and $TERM stay literal for systemd/agetty.
in_ct bash -c "cat > '${DROPIN_DIR}/autologin.conf'" <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${LOGIN_USER} --noclear --keep-baud tty%I 115200,38400,9600 \$TERM
EOF

log "reloading systemd and restarting $UNIT"
in_ct systemctl daemon-reload
in_ct systemctl restart "$UNIT"

log "done — \`pct console $CTID\` should now log in as ${LOGIN_USER} automatically"
