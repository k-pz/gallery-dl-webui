# Screens

Every screen in the app, one section per tab. Each section calls out the
content blocks, the key states, and the screenshot file to look at.

## App shell

Sticky header + tabbed body + footnote, all centered in a Mantine
`<Container size="lg">` (max ~1140px). The header sits flush with the page
background — it's a hairline + a backdrop-blur, not a separate panel.

```
┌────────────────────────────────────────────────────────────┐
│  [g] gallery-dl-webui  |  ARCHIVE                ● OK     │  ← sticky header
├────────────────────────────────────────────────────────────┤
│   Library    Jobs 1/0    Config    Maintenance            │  ← tabs
├────────────────────────────────────────────────────────────┤
│                                                            │
│                    …panel contents…                        │
│                                                            │
├────────────────────────────────────────────────────────────┤
│                  GALLERY-DL · WEBUI                        │  ← footnote
└────────────────────────────────────────────────────────────┘
```

The Jobs tab carries an inline badge showing `{running}/{scheduled}` when
there's in-flight work. When `scheduled > 0` and `running == 0`, the badge
is gray. When `running > 0`, it's blue.

Code: `App.tsx`.

## Library tab

The "what am I tracking" view.

Two stacked cards:

1. **Add a gallery** (`SubmitForm.tsx`) — the new-job form.
2. **Series** (`TargetsList.tsx`) — every known target, populated as soon
   as you submit one URL.

### Submit form

Anatomy (top to bottom):

- kicker `new job`
- `<Title order={3}>Add a gallery</Title>`
- URL row: `<TextInput label="Gallery URL">` + a primary `Download`
  button. Enter on the input submits.
- hairline
- kicker `destination & metadata` + dimmed "Optional — leave alone to use
  the configured defaults."
- `DirectoryPicker` for output dir
- Tags input + Reading direction select (side by side, both shrink)
- "Watch" checkbox with a one-line description

States:
- **No postprocess root configured**: DirectoryPicker is disabled, with a
  "Set a root in Config first" placeholder. Form still submits.
- **Submit error**: red `<Text size="sm">` immediately under the input row.
  Plus a toast.
- **Submitting**: `<Button loading>` and `<TextInput disabled>`.

Screens: `05-library-populated-{light|dark}.png` shows the form populated
with a known output dir.

### Series list

Anatomy:

- kicker `library`
- `ListHeader` — `Series {count} series` + spinner during refetch.
- `ListToolbar` — search + Status select + Extractor select + Sort by +
  direction toggle. `belowChildren` adds the All/Watched/Unwatched
  `SegmentedControl` underneath.
- list of `TargetRow`s.
- pagination footer (when >1 page).

Each `TargetRow` is multi-line:

```
[COMPLETED]  Series name (or URL)             [▶] [✕]
EXTRACTOR e2etest  RUNS 1 run  LAST RUN 1s ago  open job #1 →
[ Watch ] [ Poll every: 1d ] [ Reading direction: Use default ]
[ Tags: action ×  shounen ×  Enter to add ]
```

States:
- **Empty library** (no targets at all): card collapses to its kicker + a
  dashed-border empty hint box ("Your library is empty. Submit a gallery
  URL above to start tracking a series.").
- **Filtered to empty**: dimmed "No series match the current filters."
- **Watched + period override**: the Poll every input shows the per-target
  override; clearing falls back to the default.
- **Update busy**: switches/inputs are `disabled`, the poll/delete icons
  flip to a Mantine `Loader`.

Screens: `01-library-empty-{light|dark}.png` for the empty state,
`05-library-populated-{light|dark}.png` for the populated state.

## Jobs tab

The "what's happening" view.

Three stacked cards, conditionally rendered:

1. **Running** (`RunningJobsPanel.tsx`) — visible only when something is
   running or scheduled.
2. **Active job** (`ActiveJobCard.tsx`) — visible only when the user has
   selected a job (either by clicking a row or by following an "open job
   #N" link from the Library).
3. **Jobs** (`RecentList.tsx`) — always visible. Default filter "Active";
   becomes the queue/history view depending on the filter.

### Running panel

A condensed view of in-flight work. Kicker `running`, a mono summary
("1 running · 0 scheduled"), then one compact `.app-row` per running job
(status badge + #id + name + chapter count). Clicking a row selects it as
the Active job above.

Hidden entirely when there's nothing running and nothing scheduled.

### Active job card

The hero panel for one job. Anatomy:

- kicker `active job` + `#{id}` (mono dimmed)
- `<Title order={3}>` with the job's display name or URL. Optional
  URL subtitle (`app-url` strip) when name ≠ URL.
- Cancel + Requeue buttons (top right, contextual — only the relevant ones
  show).
- Mantine `<Stepper>` with the six-stage lifecycle, or a single filled
  Badge for terminal failure/cancellation.
- Divider.
- Detail row: "Extractor: e2etest" + "Exit code: 0" pairs.
- Optional `<Alert color="red" title="Job error">` for the worker's error
  message, and a second alert for action errors.
- `ProgressCard` with the chapter list.

States (driven by `jobStep()` in `lib/status.ts`):
- **Pending / Extracting / Running** — stepper shows current step with a
  spinner, Cancel button is visible.
- **Cancelling** — optimistic; stepper colored orange, "Cancelling…" hero
  badge replaces the running state for the moment between user click and
  server reflection.
- **Completed** — all stepper steps checked, progress bar full, Requeue
  visible.
- **Failed / Cancelled** — stepper replaced by a single filled badge,
  Requeue visible.
- **Loading** — kicker-less compact Card with a spinner and "Loading job…".

Screens: `06-jobs-active-{light|dark}.png` capture an in-flight job at
"Downloading", mid-chapter, with mixed-stage badges in the chapter list.

### Jobs (recent) list

Anatomy:
- dynamic kicker (`queue` | `all jobs` | `history`) driven by the status
  filter.
- `ListHeader` — `Jobs {count}` + spinner during refetch.
- `ListToolbar` — search + Status select + Sort by + direction toggle.
  Default sort is "Queue order".
- list of compact `.app-row`s, each clickable to select-as-active.
- pagination footer.

The compact row shape mirrors the Running panel, plus trailing action
icons (✕ cancel for non-terminal, ↻ requeue for terminal) and a URL
subtitle when name ≠ URL.

States:
- **Empty** (no jobs at all): dashed-border hint box "No jobs yet."
- **Filtered to empty**: dimmed "No jobs match the current filters."
- **Cancelling row**: optimistic — badge swaps to orange "Cancelling…" and
  the cancel icon loads.

Screens: `02-jobs-empty-{light|dark}.png` for empty,
`08-jobs-all-statuses-{light|dark}.png` for the all-statuses populated
view (shows both DOWNLOADING + COMPLETED badges side by side).

## Config tab

The settings panel. One file (`ConfigPanel.tsx`), four sub-sections in
three cards.

### Card 1: Theme

Single card, kicker `appearance`. Mantine `<SegmentedControl>` with Auto /
Light / Dark options. The selection writes to localStorage and immediately
swaps the `data-mantine-color-scheme` attribute — no reload.

### Card 2: Postprocessing + watching + concurrency

The biggest card, four sub-sections separated by dividers. Each sub-section
uses the same `<Section>` component (a styled header pattern):

1. **CBZ packing** — kicker `postprocessing`, then:
   - Root (`<TextInput>` with a mono input font).
   - Default output directory (`DirectoryPicker`).
   - Delete raw images after packing (Switch).
   - Chapter naming template (TextInput, mono).
   - Default reading direction (Select).
   - Excluded directory names (TextInput, mono, comma-separated).
2. **Polling cadence** — kicker `watching`, single "Default poll period"
   input with mono font and format hint.
3. **Parallelism** — kicker `concurrency`, one NumberInput for max parallel
   postprocess.
4. **Save changes** button + saved/error feedback. Only renders when the
   form is dirty or has a recent save result.
5. **Remembered output directories** — kicker `cache`, a `.app-surface-muted`
   block listing every previously-used output dir as mono dim text. Only
   renders when at least one is known.

### Card 3: Library backup

kicker `library backup`, title "Export / import", short description,
"Export library" + "Import library…" buttons. Import result feedback
renders as an Alert with import counts and an optional per-error list.

States:
- **Loading**: card collapses to a centered spinner + "Loading config…".
- **Dirty**: Save button visible; otherwise hidden.
- **Just saved**: green "Saved." text next to the save button.
- **Save error**: red Alert below the save button.

Screen: `03-config-{light|dark}.png` — full-page capture of every section.

## Maintenance tab

The "big destructive jobs" view (`MaintenancePanel.tsx`).

Two stacked cards:

### Card 1: Schedule maintenance

- kicker `background jobs`
- `<Title order={3}>Schedule maintenance</Title>`
- one-line description.
- Three buttons in a wrap-flex row:
  - `Schedule chapter rename` (filled, primary).
  - `Regenerate series metadata` (light variant).
  - `Rebuild library` (outline, red) — fires a native `window.confirm()`
    before scheduling.
- Below: red Alert when schedule mutation errors.

### Card 2: Maintenance jobs (history)

- kicker `history`
- `<Title order={4}>Maintenance jobs</Title>` + refetch spinner.
- Optional error Alerts.
- Either:
  - **Empty**: dashed-border hint box "No maintenance jobs yet."
  - **Populated**: bordered table with columns: ID, Job (label + raw kind
    in mono), Status (badge), Result (mono-clipped JSON or error), Actions
    (cancel × for non-terminal). Selected row is highlighted with
    `--app-surface-muted`.
- Pagination footer.
- **MaintenanceLog block** (selected job's log) — only renders when a job
  is selected.

### MaintenanceLog block

(`MaintenanceLog.tsx`.) Hidden until a job is selected; then renders below
the table after a Divider.

- Header row: kicker `log`, mono `Job #{id}`, status badge, mono counter
  (`5 / 12` or `preparing…`).
- Progress bar (striped while non-terminal).
- Bordered + muted-background `<ScrollArea h={240}>` containing the
  mono pre-formatted log lines.

States:
- **Empty**: "(no log output yet)".

Screens: `04-maintenance-empty-{light|dark}.png` and
`09-maintenance-populated-{light|dark}.png`. The populated screenshot
captures the rename_chapters job sitting in the table with the log card
expanded below it.
