# gallery-dl-webui — design handoff

A package for the incoming designer. Everything below is what's currently
shipping, plus the open questions where your judgment is wanted.

## What this app is

A small, single-user web UI in front of [gallery-dl][gd]. Submit a gallery URL,
the backend queues a job, files are downloaded and (optionally) packed into
Komga-compatible CBZs. Watched series are repolled on a schedule. The whole
thing lives on a Proxmox LXC container — no public deploy, no auth, one user.

This isn't a SaaS product. The visual register reflects that: it's a personal
archival tool, designed to read more like a reading list than a download
manager. The current theme leans into that — see [tokens.md](tokens.md).

[gd]: https://github.com/mikf/gallery-dl

## How to use this package

1. **Skim [screens.md](screens.md)** for a sense of what the app does and how
   it's organised — one section per tab.
2. **Look at the [screenshots](screenshots/)** — every tab, populated and
   empty, light and dark. Filenames are zero-padded and self-describing.
3. **Read [tokens.md](tokens.md)** for the design system — palette,
   typography, surfaces, motion. Pair it with `tokens.html` (open in a
   browser) to see them live.
4. **Read [components.md](components.md)** for the catalog of recurring
   patterns (kicker labels, status pills, list rows, etc.).
5. **Read [interactions.md](interactions.md)** for the non-static behaviour —
   realtime updates, notifications, modals.
6. **Read [open-questions.md](open-questions.md)** — that's the actual brief.
   Everything else is context.

## The handoff in one paragraph

The visual language is "editorial calm": warm off-white background, Fraunces
serif headings, IBM Plex Sans body, IBM Plex Mono for paths and numerics, a
single amber accent. Surfaces are flat with hairline borders — no heavy
shadows, no card-on-card. Status is communicated through small, low-saturation
pills, not big colored backgrounds. Live state propagates over a websocket;
the UI doesn't poll the user with toasts unless something needs attention.
Light and dark are designed as peers, not as "dark mode for the light app."

## Running it yourself

If you want to poke at the live app rather than just the screenshots:

```sh
mise install            # one-time
mise run install        # one-time
mise run dev            # both servers, ctrl-C to stop both
# open http://localhost:5173
```

It boots empty. Submit `https://mangadex.org/title/…` (or any gallery-dl
extractor) and watch the Jobs tab. Toggle Watch on a row in the Library tab
to enable repolling.

To regenerate the screenshots after a UI change:

```sh
cd frontend
pnpm exec playwright test --config=playwright.designshots.config.ts
```

The capture spec lives at `frontend/designshots/capture.spec.ts`. It boots a
FakeGallery-backed backend, seeds two URLs, and snaps each tab in both
themes. Output lands in `docs/design/screenshots/`.

## Layout

```
docs/design/
├── README.md              ← this file
├── tokens.md              ← palette, typography, spacing, motion
├── tokens.html            ← visual reference for tokens (open in browser)
├── components.md          ← shared visual patterns
├── screens.md             ← every screen + its key states
├── interactions.md        ← realtime, notifications, modals, a11y
├── open-questions.md      ← design briefs
└── screenshots/           ← captured PNGs, light + dark per state
```

## Source of truth

The current visual implementation lives in:

- `frontend/src/theme.ts` — Mantine theme + CSS variable resolver.
- `frontend/src/styles/global.css` — bespoke utilities (`.app-*` classes).
- `frontend/src/components/` — every visible component, one file each.

When the markdown disagrees with the code, the code is right. The docs are
updated alongside the implementation but they're a snapshot, not a contract.
