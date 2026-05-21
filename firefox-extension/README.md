# gallery-dl-webui — Firefox extension

A small Firefox extension that adds the page you're currently looking at to
your [gallery-dl-webui](../README.md) library in one click.

Click the toolbar icon on a manga page (e.g. mangadex, mangakakalot, …) and a
popup opens with the URL pre-filled. Fill in the optional fields — output
directory (autocompleted from the known dirs your backend exposes), tags,
reading direction, watch toggle — and hit **Add**. The extension POSTs to
`/api/downloads`, which upserts a target (the "library entry") and queues a
download.

## Files

```
firefox-extension/
  manifest.json          ← MV3 manifest (Firefox-specific gecko id)
  popup/                 ← popup shown when clicking the toolbar icon
  options/               ← settings page (backend URL)
  lib/                   ← tiny API client + storage helpers
  icons/                 ← SVG icons
```

No build step — these are plain HTML/CSS/JS files loaded directly by Firefox.

## Install (development / unsigned)

1. Make sure the backend is running and reachable from your browser (e.g.
   `http://localhost:8000`, or your NAS address).
2. Open `about:debugging#/runtime/this-firefox` in Firefox.
3. Click **Load Temporary Add-on…** and pick
   `firefox-extension/manifest.json` from this repo.
4. Click the new toolbar icon, then the gear (⚙) in the popup — or open the
   extension's preferences via `about:addons`. Enter the **Backend URL**
   (e.g. `http://localhost:8000`) and **Save**. The **Test connection**
   button hits `/api/health`.

A temporary add-on is uninstalled when Firefox restarts. To install
permanently you need to either sign it via
[addons.mozilla.org](https://addons.mozilla.org), or use Firefox Developer
Edition / Nightly / ESR with `xpinstall.signatures.required=false`.

## Backend CORS

The popup is loaded from a `moz-extension://<uuid>` origin, so the backend
must allow that origin via CORS. Two ways:

```sh
# easiest — accepts any Firefox extension install
WEBUI_CORS_ORIGIN_REGEX='moz-extension://.*'

# strict — paste the origin shown on the extension's options page
WEBUI_CORS_ORIGINS='moz-extension://abc-123-def-456'
```

Both are read at startup by `backend/src/backend/config.py:load_settings`.

In dev mode (`mise run dev`) the backend already serves CORS for the Vite
proxy at `http://localhost:5173`; the variables above are additive.

## What the extension submits

The popup mirrors the web UI's submit form. Submitting calls
`POST /api/downloads` with:

```json
{
  "url": "<active tab URL>",
  "output_dir": "<picked or default, or null>",
  "watched": true,
  "tags": ["action", "romance"],
  "reading_direction": "ltr"
}
```

`watched: true` by default — adding to the library implies "auto-poll for
new chapters". Untick the checkbox if you only want a one-shot download.

The backend handles the rest: it upserts a target (the library entry),
queues a download, and the existing CBZ postprocess + Komga conventions
apply.

## Limitations / future work

- No persistent install — needs signing or `xpinstall.signatures.required=false`.
- No content-script integration on supported manga sites (no in-page "add"
  button) — toolbar popup only.
- The output-dir picker is a `<datalist>` autocomplete, not the full
  create-new-folder picker the web UI ships.
- No deduplication hint — if the target already exists, the backend just
  re-queues a poll; the popup doesn't currently flag this.
