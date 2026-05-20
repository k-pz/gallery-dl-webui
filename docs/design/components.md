# Component catalog

The recurring visual patterns that show up across the app. Where a pattern is
bespoke (an `.app-*` class), it lives in `frontend/src/styles/global.css`.
Where it's a Mantine primitive with theme overrides, it lives in
`frontend/src/theme.ts`. Some patterns are composed inside individual
components.

## Brand mark + wordmark

The header lockup. A square amber tile with a serif `g`, the full wordmark
in Fraunces, and a mono tag `archive` separated by a hairline rule.

- Tile is 1.6rem × 1.6rem, 6px radius, `--app-accent` fill.
- Wordmark sits on a 1.35rem Fraunces baseline, weight 500.
- "ARCHIVE" tag is mono, 0.72rem, uppercase, `0.12em` letter-spacing,
  separated from the wordmark by `1px solid var(--app-border)` on the
  left edge with a 0.45rem padding.

Code: `App.tsx` (markup) + `.app-brand*` in `global.css` (styles).

## Tabs

Single hairline above the panel, no boxy backgrounds. Labels are Fraunces
1rem 500, with `-0.005em` letter-spacing. The active tab uses a 2px amber
underline. Hover doesn't change the background — only the color.

The Jobs tab carries an inline `<Badge color="blue" size="xs">{running}/{scheduled}</Badge>`
when there's in-flight work. The badge color drops to `gray` when only
scheduled (no running) jobs remain.

Code: `.app-tabs` in `global.css` + `App.tsx`.

## Cards

`Card` and `Paper` both default to `radius="md"`, `withBorder`, and use the
`.app-surface` class. That class enforces `background: var(--app-surface)`,
`border-color: var(--app-border)`, and `box-shadow: var(--app-shadow)` —
overriding Mantine's default elevation so cards look hairline-edged rather
than floating.

Anatomy of a populated card (used everywhere):

```
┌──────────────────────────────────────┐
│ KICKER LABEL (mono, uppercase)       │  ← .app-section-kicker
│ Section title (Fraunces)             │  ← <Title order=3|4>
│ Optional description (dimmed sm)     │
│                                      │
│  …content…                           │
└──────────────────────────────────────┘
```

The kicker → title pair is wrapped in `<Stack gap={4}>` to keep them tight.
The card itself uses `gap="lg"` or `gap="md"` between major sections.

## Kicker labels

Tiny all-caps mono labels that announce what each card or section is. They
read as a category, never as a heading.

```html
<span class="app-section-kicker">queue</span>
```

- Font: mono, 0.7rem.
- `letter-spacing: 0.16em`, `text-transform: uppercase`.
- Color: `--app-text-faint`.

Used at the top of every card and section, plus the bottom footnote and
the maintenance log block label. Some kickers are *dynamic* — the Jobs
list's kicker swaps between `queue`, `all jobs`, and `history` depending on
the active status filter.

## Section heading + description

Sits below the kicker. `<Title order={3}>` or `order={4}` depending on
visual weight. Description is `<Text size="sm" c="dimmed">` immediately
below.

## Hairline rule

A 1px divider in `--app-border-subtle`. Used between sections inside a card
when a `<Divider>` is too heavy — e.g. between the URL submit row and the
"destination & metadata" block in the submit form. Implemented two ways:

- `<Divider color="var(--app-border-subtle)" />` (Mantine, when in a Stack).
- `.app-rule` class — for when we need it inside arbitrary markup.

## Status pills (lists)

Borderless, low-saturation pills used in row lists to label a job's stage.

```html
<span class="app-status-pill" data-tone="active">Downloading</span>
```

Anatomy:
- pill-shaped (999px radius), padding `0.18rem 0.55rem`.
- mono, 0.7rem, uppercase, `0.08em` letter-spacing, weight 500.
- Background = `--app-surface-muted` mixed 12–14% with the tone color.
- Color = the tone color.
- Leading 0.42rem dot in `currentColor` at 0.7 opacity.

Tones: `active` (blue), `done` (green), `warn` (amber), `error` (red), `muted`.

**Note:** the app currently uses Mantine's `<Badge variant="light">` for most
status displays rather than this `.app-status-pill` class — the class exists
for cases where Mantine's badge sizing/typography isn't quite right (mono
casing, etc.). The two should converge — see
[open-questions.md](open-questions.md).

## Badges (Mantine)

`<Badge variant="light" size="sm" radius="sm">` is the default — a soft
tinted background with the tone color, slight rounding (not pill). Used for
status badges in list rows + the active job's hero badge for terminal states.

`<Badge variant="filled">` only appears for terminal states in the stepper
hero ("Failed", "Cancelled") — it's intentionally louder so the user can't
miss it.

## Health pill (header)

The "BACKEND · OK" indicator sitting next to the brand mark.

```
[●] BACKEND · OK
```

- Pill shape, 1px `--app-border`, `--app-bg-elevated` fill.
- 0.5rem leading dot in green/red/grey depending on state.
- Mono 0.72rem, uppercase, `0.08em` letter-spacing.
- States: `ok` (green dot + green text), `down` (red dot + red text),
  `loading` (faint dot, pulsing).

Code: `HealthBadge.tsx` + `.app-health*` in `global.css`.

## List rows

Two flavors:

### Compact (Jobs)

Used in `RunningJobsPanel` and `RecentList`. One line: badge, #id, name,
right-aligned count + action icons. Optional second line for URL subtitle
when the row's name differs from the URL.

```
[DOWNLOADING] #2  https://e2e.test/very-slow          4 ch.  ✕
```

The whole row is `role="button"`, clickable, with `Enter`/`Space` keyboard
activation. Hover and selected states share the same `--app-surface-muted`
background; selected adds a 1px border. Selection persists across re-renders.

Code: `.app-row` in `global.css`, used by `RunningJobsPanel.tsx`,
`RecentList.tsx`.

### Expanded (Library)

Used in `TargetsList`. Multi-line: status badge + name + open-job link, then
metadata row (extractor, runs, last run), then a control row (watch switch,
poll period, reading direction), then a tags input. Rows are separated by
`1px solid var(--app-border-subtle)` rather than the pill-rounded `.app-row`
treatment.

Each row has two trailing action icons: ▶ poll-now (amber), ✕ delete (red,
subtle).

## URL strip

Monospaced subtitle used wherever we surface a URL.

```html
<Text className="app-url" title={url}>{url}</Text>
```

- Mono, 0.78rem.
- Color `--app-text-faint`.
- `word-break: break-all` — long URLs don't overflow the row.

## Meta labels (Library row)

A label-then-value pair separated by uppercase letter-spacing on the label.
Used in the Library row's "EXTRACTOR e2etest", "RUNS 1 run" etc strip.

Anatomy: two spans inside a `<Text size="xs" c="dimmed">`. The label has
`letter-spacing: 0.06em` and `text-transform: uppercase`. The value uses
mono only when it's an identifier (path, extractor) — counts and "—"
placeholders stay sans.

## Action icons

Trailing icons on list rows. Default to:

- `<ActionIcon variant="subtle" color="red">✕</ActionIcon>` for destructive.
- `<ActionIcon variant="light" color="amber">▶</ActionIcon>` for affirmative.
- `<ActionIcon variant="default" size="lg">↑/↓</ActionIcon>` for sort-direction.

All have `Tooltip` wrappers with `withArrow`.

## Sort direction toggle

A small action button next to the "Sort by" Select that flips ↑/↓. The
tooltip describes the direction in human terms ("A → Z", "Next to process
first") rather than literal "asc/desc". Code: `SortDirToggle.tsx`.

## Toolbar (list filters)

`ListToolbar.tsx` — a flex row with a search input and a slot for
domain-specific `Select`s. Optional `belowChildren` slot renders a second
row beneath for things like the "All / Watched / Unwatched" segmented
control on the Library tab.

Search input is always present, has flex-1 layout, and uses a `minWidth`
prop so it doesn't collapse when filters wrap on narrow viewports.

## Pagination

`ListPagination.tsx` — only renders when `totalPages > 1`. Anatomy: left
side reads "23–34 of 87" (mono-ish dimmed); right side is Mantine's
`<Pagination size="sm" siblings={1} boundaries={1}>`.

## Stepper (active job)

Mantine's `<Stepper size="xs" iconSize={20}>` rendered horizontally with
six steps: Scheduled → Fetching metadata → Downloading → Downloaded →
Processing → Completed. The active step shows a spinner, completed steps
get a check, failed/cancelled fall back to a Badge replacement (see below).

For terminal failure/cancel, the stepper is *replaced* by a single large
`<Badge variant="filled">Failed</Badge>` or `Cancelled` — the per-step grid
disappears entirely.

## Progress card

Visible only on the active job view. Two parts:

1. **Header row** — kicker "progress" on the left, mono counter ("3 / 12
   chapters") on the right.
2. **Progress bar** — Mantine `<Progress size="md" radius="sm">`. While
   non-terminal, it's `striped + animated` in the amber accent. Once
   terminal, the stripes stop.
3. **Chapter list** — bordered + muted-background scrollable box (220px
   tall), one row per chapter with the chapter name (mono) and a stage
   badge (Mantine `light` variant, color per stage). Rows separated by
   1px hairlines.

## Tables

The only `Table` instance is the maintenance jobs table. Uses Mantine's
`Table verticalSpacing="sm" highlightOnHover stickyHeader` inside a bordered
box with `radius="md"` and `overflow: hidden`. Selected row gets
`backgroundColor: var(--app-surface-muted)`.

## Forms

All inputs use Mantine's `radius="md"` default. Patterns:

- **Label** above the field.
- **Description** beneath the label in `c="dimmed" size="xs"`.
- **Inline error** below the field via Mantine's built-in `error` prop, or
  free `<Text c="red" size="sm">` for submit-level errors.

Path inputs (postprocess root, output dir, chapter template, excluded
dirs) get `styles={{ input: { fontFamily: "var(--app-mono)" } }}` so the
typed path reads as code.

## DirectoryPicker

Composite: a searchable Mantine `Select` showing all known output dirs,
plus a `+` ActionIcon that toggles an inline "create folder" form. The
inline form is a `<Paper>` with `backgroundColor: var(--app-surface-muted)`
containing a TextInput + Create / Cancel buttons. The Select renders
disabled when `postprocess_root` is unset, with a "Set a root in Config
first" placeholder.

## Footnote

A single mono line at the bottom of every page.

```
GALLERY-DL · WEBUI
```

- mono, 0.7rem, uppercase, `0.1em` letter-spacing.
- color `--app-text-faint`.
- centered, 1.5rem top padding.

Closes the page calmly. Visible in every screenshot.

## Notifications

Mantine `Notifications position="top-right"`. Toasts come from mutation
callbacks (`onSuccess`/`onError`). Colors map to outcome:

- `green` — successful create/queue
- `blue` — informational (Poll queued, Requeued)
- `orange` — soft warning (Cancel requested)
- `gray` — neutral (Target removed)
- `red` — failure

Title is short; message is one sentence ending in a period.

## Modals + confirms

Two patterns currently:

1. **`window.confirm()`** — used for destructive actions (delete target,
   rebuild library). Native browser dialog. **This is a known rough edge**
   — see [open-questions.md](open-questions.md).
2. **Inline expand** — the DirectoryPicker's "create folder" form expands
   inline within the picker rather than opening a modal. This is the
   preferred pattern.

There are no Mantine `Modal` instances in the app today.
