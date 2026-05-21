# Docs

Companion to the top-level [`README.md`](../README.md) — the README covers
"how do I run it"; everything here covers "how does it actually work".

These pages also feed the [auto-published wiki](https://github.com/k-pz/gallery-dl-webui/wiki)
via `scripts/build-wiki.py` on every push to `main`.

> **Disclaimer — AI-authored code.** Substantially all of the source in this
> repository, including these docs, was written by
> [Claude Code](https://www.anthropic.com/claude-code), Anthropic's AI coding
> assistant. Read and review accordingly.

## Contents

- [Architecture](architecture.md) — what it is, process model, deployment
  topology, repository layout.
- [Backend](backend.md) — application factory, settings, database, per-domain
  module shape.
- [Download pipeline](pipeline.md) — the worker, gallery-dl integration, CBZ
  postprocessing, progress accounting.
- [Frontend](frontend.md) — stack, generated API client, components, state
  strategy, tests.
- [Lifecycles](lifecycles.md) — end-to-end traces: single download, watched
  re-poll, cancel, boot recovery.
- [Testing](testing.md) — backend + frontend test strategy.
- [Deployment](deployment.md) — local dev and Proxmox LXC production setup.
- [Design decisions](decisions.md) — the *why* behind the load-bearing
  choices.

## Where to look next

- **New backend route or schema change** → add to the relevant domain's
  `router.py` + `schemas.py`, run the backend, `mise run generate:client`.
  See [Backend](backend.md#per-domain-modules).
- **Worker behavior** → [Download pipeline](pipeline.md): `downloads/worker.py`
  for orchestration, `downloads/gallery.py` for gallery-dl integration,
  `downloads/postprocess.py` for CBZ packing.
- **Watched-target scheduling** → [Backend](backend.md#targetspollerpy):
  `targets/poller.py` + `targets/utils.py`.
- **Path/output validation** → [Backend](backend.md#output_dirs):
  `output_dirs/utils.py`.
- **Frontend UI behavior** → [Frontend](frontend.md): `frontend/src/components/`.
  Most components are self-contained; cross-cutting concerns live in
  `frontend/src/lib/`.
- **Deployment** → [Deployment](deployment.md): `scripts/proxmox-*.sh` and
  `mise.toml`. The systemd unit itself is written inline in
  `proxmox-install.sh`.
