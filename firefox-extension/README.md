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

A temporary add-on is uninstalled when Firefox restarts. The next two
sections walk through the two ways to install it permanently.

## Permanent install — option A: self-distribute a signed `.xpi` (recommended)

Works in every Firefox channel (Release, ESR, mobile). Mozilla signs the
build for you but doesn't list it publicly. You'll need a (free)
[addons.mozilla.org](https://addons.mozilla.org) account.

1. **Package the source.** From the repo root:
   ```sh
   cd firefox-extension
   zip -r ../gallery-dl-webui-extension.zip . -x '*.DS_Store'
   ```
   You should get a single `gallery-dl-webui-extension.zip` whose root
   contains `manifest.json` directly (not nested in a folder).

2. **Open the Developer Hub.** Sign in at
   <https://addons.mozilla.org/developers/> and click
   **Submit a New Add-on**.

3. **Pick "On your own".** When asked _"How to distribute this version?"_,
   choose **On your own**. This makes the listing private — only you get
   the download link.

4. **Upload the `.zip`.** Mozilla's automated validator runs (same checks
   as `web-ext lint`, which already passes here). Approve the
   source-code-and-license prompts.

5. **Wait for signing.** Usually a minute or two for a "Listed: No"
   submission. When it's done, the version page exposes a **Download**
   button for the signed `.xpi`.

6. **Install in Firefox.** Drag the signed `.xpi` onto a Firefox window
   (or `about:addons` → gear → _Install Add-on From File…_). Confirm the
   permission prompt.

7. **Updates.** Repeat with the version bumped in `manifest.json`. To
   automate the upload/sign/download cycle, use
   [`web-ext sign`](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/#web-ext-sign)
   with [AMO API credentials](https://addons.mozilla.org/developers/addon/api/key/):
   ```sh
   cd firefox-extension
   npx web-ext sign \
     --api-key="$AMO_JWT_ISSUER" \
     --api-secret="$AMO_JWT_SECRET" \
     --channel=unlisted
   ```
   The signed `.xpi` lands in `web-ext-artifacts/`.

## Permanent install — option B: disable signature enforcement (Dev Edition / Nightly)

No AMO involvement, but **only works on Firefox Developer Edition, Nightly,
or an Unbranded build** — Release and ESR ignore the preference.

1. **Install Firefox Developer Edition.** Download from
   <https://www.mozilla.org/firefox/developer/>. Run it alongside your
   regular Firefox (it uses a separate profile).

2. **Disable signature enforcement.** Open `about:config`, accept the
   warning, then set:
   ```
   xpinstall.signatures.required  →  false
   ```

3. **Build the `.xpi`.** From the repo root:
   ```sh
   cd firefox-extension
   zip -r ../gallery-dl-webui-extension.xpi . -x '*.DS_Store'
   ```
   (`.xpi` is just a renamed `.zip`.)

4. **Install the `.xpi`.** Open `about:addons` → gear icon (top right) →
   _Install Add-on From File…_ → pick `gallery-dl-webui-extension.xpi` →
   confirm.

5. **Verify.** The extension stays installed across restarts. Open the
   options page (`about:addons` → the extension → _Preferences_) and set
   your backend URL.

To update, bump the `version` in `manifest.json`, rebuild the `.xpi`, and
re-install via the same flow (Firefox replaces the existing copy because
`browser_specific_settings.gecko.id` matches).

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
