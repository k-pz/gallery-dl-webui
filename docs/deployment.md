# Deployment

## Local

`mise install && mise run install && mise run dev`. See the top-level
[`README.md`](../README.md) and `mise.toml`.

## Proxmox LXC

`scripts/proxmox-install.sh` does the full lift on a Proxmox VE host:

1. Optionally mount a CIFS share on the host (uid=100000/gid=110000 so the
   unprivileged CT can write through the bind mount), add an fstab entry.
2. Create the CT (Debian 13 template, default unprivileged, `vmbr0`, 64 GB,
   2 cores, 1 GB RAM — all overridable).
3. `pct set <CTID> -mp0 <host_dir>,mp=/mnt/nas` if a NAS was provided.
4. Bootstrap: `apt-get install ffmpeg git ca-certificates curl sudo`,
   create `gallery-dl` system user, install `mise` to `/usr/local/bin`.
5. Push source via `tar | pct exec ... tar -x`.
6. `mise run install:prod` (uv sync `--frozen --no-dev`, pnpm install).
7. `mise run build` (Vite production bundle).
8. Write `/etc/systemd/system/gallery-dl-webui.service`:
   - `ExecStart=/usr/local/bin/mise run -C ${APP_DIR} serve:backend`
   - Sandbox: `ProtectSystem=strict`, `ProtectHome=yes`,
     `NoNewPrivileges=yes`, `PrivateTmp=yes`, `KillMode=mixed`.
   - `ReadWritePaths=${DATA_DIR}` plus an optional `extra-rw-paths.conf`
     drop-in for `EXTRA_RW_PATHS` (e.g. `/mnt/nas/manga`).
9. Enable + start the service. Logs are `journalctl -u gallery-dl-webui`.

`proxmox-update.sh` re-syncs the source (preserving `.venv` /
`node_modules`), reinstalls, rebuilds, and restarts. It also includes a
one-time migration from older `ExecStart=` lines.

`proxmox-uninstall.sh` stops + destroys the CT, with a confirmation prompt
unless `FORCE=1`.

`_proxmox-lib.sh` provides `log/die/in_ct/in_ct_sh/as_app` helpers shared
by the three host scripts.

### In-CT update (`update`)

`scripts/lxc-update.sh` is a self-contained updater that runs **inside** the
CT — no Proxmox host access needed. `proxmox-install.sh` drops it at
`/usr/local/bin/update`, and `proxmox-update.sh` refreshes that copy on
every host-side run.

```sh
pct console <CTID>    # root autologin, set up by proxmox-install.sh
update                # clone main, mise install:prod + build, restart unit
REPO_REF=some-branch update    # pin a different ref
```

Pre-install bootstrap (no local copy yet):

```sh
curl -fsSL https://raw.githubusercontent.com/k-pz/gallery-dl-webui/main/scripts/lxc-update.sh \
    | bash
```

It mirrors `proxmox-update.sh`: preserves `backend/.venv` and
`frontend/node_modules`, runs `mise run install:prod` + `mise run build`
as `gallery-dl`, applies the `ExecStart=` migration, then
`systemctl restart --no-block` and waits up to 30 s for active. Defaults
the clone to HTTPS so it works without a CT-side SSH key.
