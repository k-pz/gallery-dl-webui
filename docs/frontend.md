# Frontend

The React app under `frontend/`, the auto-generated API client, the shape
of the components, and the state strategy.

## Stack

- **Vite 8** + **React 19** + **TypeScript** (`tsc -b --noEmit` for
  typecheck-only; Vite bundles).
- **Mantine 9** (`@mantine/core` + `@mantine/notifications`) for everything
  visual.
- **TanStack Query 5** for server state.
- **Biome 2** for lint + format (replaces ESLint + Prettier).
- **Vitest** for unit tests, **Playwright** for e2e.

## Generated API client

Everything under `frontend/src/api/` is produced by
`@hey-api/openapi-ts` from the live backend's `/openapi.json`. Two plugins
are configured (`openapi-ts.config.ts`):

- `@hey-api/client-fetch` — the low-level `fetch`-based client.
- `@tanstack/react-query` — produces typed `*Options()` /
  `*Mutation()` builders so components write:

  ```ts
  const { data } = useQuery(listTargetsOptions());
  const create = useMutation({ ...createDownloadMutation(), onSuccess: ... });
  ```

The `client.gen.ts` `setConfig({ baseUrl: "" })` lets requests be relative —
in dev they go through the Vite proxy to `:8000`, in prod they hit the same
origin that's serving the SPA.

After backend route/schema changes, regenerate via `mise run generate:client`
(with the dev server running so `/openapi.json` is reachable). Generated
files are committed.

## Top-level structure

`main.tsx` wraps the tree in `<MantineProvider defaultColorScheme="auto">`,
`<Notifications position="top-right" />`, and `<QueryClientProvider>`. The
preceding inline `<script>` in `index.html` reads the persisted color scheme
from `localStorage` and sets `data-mantine-color-scheme` before React mounts
— prevents the FOUC flash.

`App.tsx` is the only routing-ish component (Mantine `<Tabs>`). Three tabs:

- **Library** — `SubmitForm` + `TargetsList`.
- **Jobs** — `ActiveJobCard` (if a job is selected) + `RecentList`.
- **Config** — `ConfigPanel`.

Clicking "open job #X" on a target jumps to the Jobs tab with that download
selected (via `openJob` callback).

## Components

| Component             | What it does                                                                                          |
|-----------------------|--------------------------------------------------------------------------------------------------------|
| `SubmitForm`          | URL input + `DirectoryPicker` for output dir; `POST /api/downloads` on submit. Notification on success/error. Seeds the picker with `postprocess_default_output_dir` until the user touches it. |
| `TargetsList`         | Library tab. Polled every `REFETCH_LIST_MS` (2 s). Filters: search, watched/unwatched, status (`active`/`completed`/`failed`/`no-runs`), extractor, sort. Each row has a `Watch` switch, period override input, "Poll now", "Delete", and "open job #N" link. |
| `RecentList`          | Recent downloads. Same polling. Filters: search, status, sort. Rows are clickable to open in `ActiveJobCard`; cancel + requeue inline. |
| `ActiveJobCard`       | Selected job's full view. Polls every `REFETCH_ACTIVE_MS` (1 s) but only while non-terminal. Shows a Mantine `<Stepper>` with the 5-step user-facing job lifecycle ("Scheduled → Fetching metadata → Downloading → Processing → Completed"), plus `ProgressCard`. |
| `ProgressCard`        | Renders the per-chapter list returned by `GET /api/downloads/{id}/progress`. Each chapter has a colored stage badge. Top-level progress bar is `(non-downloading chapters) / (total chapters)`. |
| `ConfigPanel`         | Edits postprocess root, default output dir, delete_raw, default watch period; theme switcher; library export/import. |
| `DirectoryPicker`     | Reusable `Select` + "create folder" inline form. Loads `/api/output-dirs` only when `enabled` (`postprocess_root` is set). Used by both `SubmitForm` and `ConfigPanel`. |
| `HealthBadge`         | Tiny "backend OK / unreachable" pill in the header. Plain `useQuery(getHealthOptions())`. |
| `ListHeader`          | "Title + count + spinner" row shared by Library and Recent. Shows `<visible> of <total>` when filters are active. |
| `ListToolbar`         | Search input + slot for domain-specific filter `Select`s; second slot below for things like the watched-segment control. |

## Lib helpers

| File                  | Exports                                                                                                                                   |
|-----------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| `status.ts`           | `Status`, `statusColor`, `isTerminal`, `isActive`, `isCancellable`, the `JOB_STEPS` constant, `jobStep(...)`. Owns the UI-only `CANCELLING_LABEL` (`"cancelling"`) which is *not* a backend status. |
| `polling.ts`          | `REFETCH_ACTIVE_MS = 1000`, `REFETCH_LIST_MS = 2000`.                                                                                     |
| `invalidate.ts`       | `useDataInvalidators()` hook returning `{ downloads, targets, config, outputDirs, download(id) }` — named invalidators reused everywhere. |
| `apiError.ts`         | `extractErrorMessage(err)` — peeks at FastAPI's `detail` shape before falling back to `Error.message`.                                    |
| `optimisticCancel.ts` | `useOptimisticCancel(id, status)` (single job) + `useOptimisticCancelMany(items)` (list). Shows "Cancelling…" between the user clicking Cancel and the server reflecting it. Auto-clears on terminal. |
| `listFilters.ts`      | `makeNeedleMatcher(needle, ...getters)` — case-insensitive substring match over an arbitrary set of field getters.                        |
| `time.ts`             | `formatRel(iso)` → `"3h ago"` etc.                                                                                                        |
| `libraryBackup.ts`    | `exportLibrary()` / `importLibrary(file)` — bypass the generated client because YAML isn't modelled there. Triggers a browser download for export. |

## State strategy

There's effectively no global client state. All data is owned by TanStack
Query:

- Lists poll on a fixed interval (2 s) and aren't paginated.
- The active-job view polls on a faster interval (1 s) and self-disables
  once the job is terminal (via `refetchInterval: (q) => isTerminal(...) ?
  false : ...`).
- Mutations call `useDataInvalidators` after success — there's no manual
  `setQueryData` write-through.
- Two pieces of genuinely-UI state escape this rule: the optimistic-cancel
  flag (per-component `useState`) and the selected job id / current tab
  (top-level `useState` in `App.tsx`).

## Tests

- **`*.test.ts` / `*.test.tsx`** — vitest unit tests for `lib/` helpers and
  selected components. `src/test/setup.ts` is loaded by `vitest.config.ts`
  for `jest-dom` matchers.
- **`e2e/`** — Playwright specs run against the real frontend wired to a
  `FakeGallery`-backed backend (`backend/tests/e2e_server.py`). Playwright
  itself spawns both servers — see `playwright.config.ts`. Runs on
  `:8765` (backend) / `:5174` (frontend) so it doesn't collide with `mise
  run dev`.

See [Testing](testing.md) for the full test strategy across backend +
frontend.
