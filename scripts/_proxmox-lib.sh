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

# Auto-detect a private SSH key on the Proxmox host suitable for git over
# SSH. Prints the path on stdout; returns non-zero if none found.
detect_host_ssh_key() {
    local candidate
    for candidate in /root/.ssh/id_ed25519 /root/.ssh/id_rsa /root/.ssh/id_ecdsa; do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Copy the host's SSH key into the CT's /root/.ssh/ so the in-CT `update`
# command (lxc-update.sh) can pull the repo over SSH using the same identity
# the Proxmox host uses. Idempotent — safe to call from install or update.
#
# HOST_SSH_KEY controls the source:
#   __AUTO__ (default) → detect_host_ssh_key
#   ""                 → skip (no key installed; in-CT updates fall back to HTTPS)
#   <path>             → use that file
install_host_ssh_key() {
    # Preserve empty-vs-unset: HOST_SSH_KEY="" explicitly opts out, while
    # leaving it unset means "auto-detect".
    local key="${HOST_SSH_KEY-__AUTO__}"
    if [[ "$key" == "__AUTO__" ]]; then
        key="$(detect_host_ssh_key || true)"
    fi

    if [[ -z "$key" ]]; then
        log "no host SSH key found (set HOST_SSH_KEY or drop one at /root/.ssh/id_*) — in-CT 'update' will use HTTPS"
        return 0
    fi

    [[ -f "$key" ]] || die "HOST_SSH_KEY=$key does not exist"

    local name
    name="$(basename "$key")"

    log "installing host SSH key ($key → CT:/root/.ssh/$name) for git over SSH"
    in_ct install -d -m 0700 -o root -g root /root/.ssh
    pct push "$CTID" "$key" "/root/.ssh/$name" --perms 0600 --user root --group root
    if [[ -f "${key}.pub" ]]; then
        pct push "$CTID" "${key}.pub" "/root/.ssh/${name}.pub" \
            --perms 0644 --user root --group root
    fi

    # Seed github.com host keys so the first git-over-ssh call doesn't prompt
    # or fail host-key verification. accept-new is a belt-and-braces fallback
    # if ssh-keyscan can't reach github at install time.
    in_ct_sh "
        set -e
        touch /root/.ssh/known_hosts
        ssh-keyscan -t ed25519,rsa github.com 2>/dev/null >> /root/.ssh/known_hosts || true
        sort -u /root/.ssh/known_hosts -o /root/.ssh/known_hosts
        chmod 0644 /root/.ssh/known_hosts

        if ! grep -q '^Host github.com\$' /root/.ssh/config 2>/dev/null; then
            printf 'Host github.com\n    StrictHostKeyChecking accept-new\n\n' >> /root/.ssh/config
            chmod 0600 /root/.ssh/config
        fi
    "
}
