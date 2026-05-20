# Design tokens

The complete set of design tokens defined in `frontend/src/theme.ts` and
`frontend/src/styles/global.css`. Open `tokens.html` in a browser to see
them visualised.

## Color

### Brand ramps

Two Mantine color scales are defined: **amber** (the accent) and **ink**
(neutral). The numbers are Mantine's standard 0–9 index — 0 = lightest,
9 = darkest. The light theme uses `amber[6]` as accent, dark uses `amber[4]`
(more luminous so it carries through against the dark surface).

**Amber** — the only chromatic family in the system. Used on the accent
(brand mark fill, link color, active tab underline, "Download" button,
striped progress fill, ↻ requeue icon).

| Step      | Hex       | Notes                                              |
|-----------|-----------|----------------------------------------------------|
| amber.0   | `#fbf6ec` | almost white; used as a faint tint surface         |
| amber.1   | `#f3e6c8` |                                                    |
| amber.2   | `#ead29c` |                                                    |
| amber.3   | `#dfbc6f` |                                                    |
| amber.4   | `#d3a64a` | **dark-mode accent**                                |
| amber.5   | `#c89134` | also used in `::selection` (with alpha)            |
| amber.6   | `#b07a2b` | **light-mode accent**                               |
| amber.7   | `#8d6121` |                                                    |
| amber.8   | `#6b491a` |                                                    |
| amber.9   | `#4a3212` | darkest; not used directly                          |

**Ink** — the neutral family. Not used directly as Mantine `color="ink"` —
the per-scheme surface tokens below are derived from it (e.g. dark `--app-bg`
sits between ink.9 and ink.8). Light-mode background is its own value
(`#f7f2e8`) outside the ink ramp.

| Step      | Hex       |
|-----------|-----------|
| ink.0     | `#f6f3ee` |
| ink.1     | `#ebe6dc` |
| ink.2     | `#d2cbbe` |
| ink.3     | `#aba391` |
| ink.4     | `#807866` |
| ink.5     | `#5a5343` |
| ink.6     | `#3e3829` |
| ink.7     | `#2a251a` |
| ink.8     | `#1a160e` |
| ink.9     | `#0e0c07` |

### Surface + text tokens (per scheme)

These are the variables that every component reads. They're set by the
`cssVariablesResolver` in `theme.ts` based on `data-mantine-color-scheme`.

**Light**

| Token                  | Value                                              |
|------------------------|----------------------------------------------------|
| `--app-bg`             | `#f7f2e8` (warm off-white)                         |
| `--app-bg-elevated`    | `#fbf7ee` (slightly cooler — for the health pill)  |
| `--app-surface`        | `#ffffff` (cards)                                  |
| `--app-surface-muted`  | `#f1ebde` (nested boxes, hover row, log panels)    |
| `--app-border`         | `rgba(46, 36, 18, 0.14)` — primary 14% ink         |
| `--app-border-subtle`  | `rgba(46, 36, 18, 0.08)` — dividers + row gaps     |
| `--app-text`           | `#1a160e` (= ink.8)                                |
| `--app-text-muted`     | `#5a5343` (= ink.5)                                |
| `--app-text-faint`     | `#807866` (= ink.4)                                |
| `--app-accent`         | `#b07a2b` (= amber.6)                              |

**Dark**

| Token                  | Value                                              |
|------------------------|----------------------------------------------------|
| `--app-bg`             | `#16130d` (deep ink, slightly warm)                |
| `--app-bg-elevated`    | `#1d1912`                                          |
| `--app-surface`        | `#1f1b14` (cards)                                  |
| `--app-surface-muted`  | `#27221a` (nested boxes, hover row)                |
| `--app-border`         | `rgba(214, 198, 168, 0.14)` — primary 14% cream    |
| `--app-border-subtle`  | `rgba(214, 198, 168, 0.07)`                        |
| `--app-text`           | `#ebe4d3` (warm cream)                             |
| `--app-text-muted`     | `#9d9582`                                          |
| `--app-text-faint`     | `#6f6859`                                          |
| `--app-accent`         | `#d3a64a` (= amber.4)                              |

### Semantic colors

Status communication uses Mantine's named colors at the `light` variant
(borderless badge with low-saturation background tint).

| Status        | Mantine color | Where it appears                              |
|---------------|---------------|------------------------------------------------|
| pending       | `gray`        | "Scheduled" badge                              |
| extracting    | `yellow`      | "Fetching metadata" badge                      |
| running       | `blue`        | "Downloading" badge, in-flight jobs panel      |
| cancelling    | `orange`      | optimistic "Cancelling…" badge                 |
| completed     | `green`       | terminal success                                |
| failed        | `red`         | terminal failure                                |
| cancelled     | `orange`      | terminal cancel                                 |

Chapter-stage colors (rendered as small per-row badges in the progress card):

| Stage        | Mantine color |
|--------------|---------------|
| downloading  | `blue`        |
| downloaded   | `cyan`        |
| processing   | `yellow`      |
| completed    | `green`       |

### Health pill colors

The "BACKEND · OK" pill in the header uses three small literal colors that
sit slightly outside the Mantine scale because they need to read at a glance
on both light and dark surfaces:

| State         | Color     |
|---------------|-----------|
| ok            | `#4f9e62` (muted green)                         |
| down          | `#c14d3a` (muted red)                           |
| loading       | `var(--app-text-faint)` (pulses)               |

## Typography

Three stacks, all served from Google Fonts via `@import` in `global.css`.

| Token          | Stack                                                                                          | Role                                    |
|----------------|------------------------------------------------------------------------------------------------|-----------------------------------------|
| sans (body)    | `"IBM Plex Sans", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif` | All body copy + Mantine inputs       |
| serif (display)| `"Fraunces", "IBM Plex Serif", Georgia, "Times New Roman", serif`                              | Brand mark, tab labels, every heading  |
| mono           | `"IBM Plex Mono", ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, Consolas, monospace`  | Paths, URLs, counts, kicker labels     |

Fraunces is loaded with its variable optical-size axis (`opsz,wght@9..144`),
default `opsz=18` set on `body`. Headings inherit the variable axis so they
read with a heavier optical weight at larger sizes.

### Heading scale

| Token | Size  | Line height | Weight |
|-------|-------|-------------|--------|
| h1    | 36px  | 1.1         | 500    |
| h2    | 26px  | 1.2         | 500    |
| h3    | 20px  | 1.3         | 500    |
| h4    | 17px  | 1.35        | 600    |
| h5    | 15px  | 1.4         | 600    |

All headings get `text-wrap: balance` and inherit the serif stack.

### Editorial details

- `font-feature-settings: "ss01" 1, "ss02" 1, "cv11" 1` on `body` —
  enables IBM Plex Sans's editorial stylistic sets.
- `letter-spacing: -0.01em` on the brand wordmark and `-0.005em` on the tab
  labels — typical for Fraunces at display sizes.
- Kicker labels (the all-caps mono micro-labels above section titles) use
  `letter-spacing: 0.16em` and `text-transform: uppercase` at `0.7rem`.

## Spacing

Mantine's default spacing scale, used via `gap="md"` etc. The actual values
(remmed at the root font-size, 16px by default):

| Token | px   |
|-------|------|
| xs    | 10px |
| sm    | 12px |
| md    | 16px |
| lg    | 20px |
| xl    | 32px |

Common composition pattern: `<Stack gap="lg">` for sections within a Card,
`<Stack gap={4}>` (raw 4px) for kicker → title pairs, `<Stack gap="md">`
for the toolbar + list inside a panel.

## Radius

Mantine defaults except `defaultRadius: "md"`.

| Token | px   | Where                                       |
|-------|------|----------------------------------------------|
| xs    | 2px  | rarely                                       |
| sm    | 4px  | badges                                       |
| md    | 8px  | cards, buttons, inputs, list rows            |
| lg    | 16px | not currently used                           |
| xl    | 32px | not currently used                           |

Note: status pills, health pill, and the chapter-stage badges use `999px`
for full-pill rounding, not the radius scale.

## Elevation

Cards have a minimal two-stop shadow defined per scheme:

- **Light**: `0 1px 0 rgba(46, 36, 18, 0.04), 0 12px 28px -22px rgba(46, 36, 18, 0.25)`
- **Dark**:  `0 1px 0 rgba(0, 0, 0, 0.35), 0 18px 40px -28px rgba(0, 0, 0, 0.55)`

The 1px stop is a hairline rim; the long, soft second stop sits the card
above the page background. No multi-stop "elevation system" — every card
gets this one shadow.

The sticky header backdrop uses `backdrop-filter: saturate(140%) blur(10px)`
plus an 88% opacity background — the warm bg shows through slightly.

## Motion

Lightweight. There is no animation system or motion tokens.

| Where                  | Spec                                                |
|------------------------|------------------------------------------------------|
| Tab label hover/active | `color 0.18s ease, border-color 0.18s ease`         |
| List row hover         | `background-color 0.15s ease, border-color 0.15s ease` |
| Health pill loading    | `app-pulse` keyframe, 1.2s ease-in-out infinite      |
| Progress bar (active)  | Mantine's built-in `striped + animated`              |
| Stepper                | Mantine's built-in fade between active steps         |

Nothing else easings, springs, or transitions — by intent. The app aims to
read as "calm and static-feeling" until something changes.

## Iconography

There are essentially no icons. The app uses Unicode glyphs:

| Glyph | Where                                       |
|-------|---------------------------------------------|
| `g`   | Brand mark (Fraunces, ss01)                 |
| `✕`   | Cancel / delete (in lists)                  |
| `↻`   | Requeue (in lists)                          |
| `▶`   | Poll target now (in Library)                |
| `+`   | Create folder (DirectoryPicker)             |
| `×`   | Close create-folder form                    |
| `↑/↓` | Sort direction toggle                       |
| `·`   | Visual separator (health pill, footnote)   |

This is a deliberate constraint — see [open-questions.md](open-questions.md)
for whether an icon set should be introduced.
