# Copy + Responsive UX Refinement — Design

**Date:** 2026-06-08
**Branch:** `feat/ux-copy-refinement`
**Status:** Approved (design), pending implementation plan

## Goal

Refine the copy and the design to improve UI/UX across the gallery-dl-webui
frontend — **desktop, but phones especially**. This is a *consistency and
completeness* effort against the existing editorial "paper" design system, not a
new aesthetic. All work uses the established `--app-*` / `--tone-*` tokens and
the existing utility/`.icon-btn`/`.pill` vocabulary.

## Context

The design system itself is well-executed (sticky flat header, drawer nav at
≤768px, container-query row wrapping, stacked maintenance table). A read-only
audit (6 agents) found phone UX is undercut by a few *systemic* issues rather
than many isolated ones, and copy leaks raw backend vocabulary in a handful of
user-facing spots. Crucially, **the 44px touch-target variant
(`.icon-btn[data-size="lg"]`) and the wrap-friendly Group pattern already exist**
— they are applied inconsistently. So most diffs are small and idiomatic.

### Current responsive foundation (verified)

- **No custom `theme.breakpoints`** — Mantine defaults exist but are unused; all
  responsiveness is hand-rolled CSS `@media (max-width: …)` plus one
  `@container` query.
- **No PostCSS config and no `postcss-preset-mantine`** — Mantine v9 runs on its
  static CSS, so the `smaller-than` mixin is unavailable and `@media` cannot read
  CSS variables natively.
- Breakpoint literals scattered across `global.css`:
  `@container (max-width: 480px)` (the `.app-row` wrap), `540px` (phone gutters /
  header / active-job declutter), `640px` (maintenance table → stacked cards),
  `768px` (tabs → drawer nav), `880px` (Jobs master-detail grid → single column).
- `env(safe-area-inset-*)` is used **only** by the drawer; header and body are
  unprotected.
- No `prefers-reduced-motion` handling anywhere.
- `lib/status.ts` exposes `jobStatusLabel()` / `chapterStageLabel()` /
  `JOB_STEPS`; several surfaces bypass these and print raw backend tokens.

## Decisions (locked)

1. **Canonical noun:** `series` is the tracked object everywhere; `gallery`
   survives **only** as the literal `Gallery URL` input label (gallery-dl's own
   term for what the user pastes). Boundary: *you submit a gallery URL, it becomes
   a tracked series.*
2. **Touch targets:** promote actionable icon buttons to **44px at phone widths
   only** (≤540px). Desktop keeps its deliberately tight 26px density.
3. **Jargon:** plain-language lead, precise term in parentheses
   (e.g. "safe to run repeatedly (idempotent)"). Fix outright-ambiguous lines
   fully.
4. **Maintenance result cell:** tap-to-expand inline, collapsed by default.
5. **Breakpoint mechanism:** add `postcss-custom-media` (a dev-dep +
   `postcss.config.cjs`) so every media query reads a named token from one
   definition block. Also add `theme.breakpoints` for JS-side viewport logic.

## Workstreams

Sequenced **foundation → structural → copy → polish**. Each is independently
reviewable.

### A. Breakpoint foundation (refactor, no behavior change)

- Add `postcss-custom-media` + `postcss.config.cjs`.
- Define named custom-media tokens in one block at the top of `global.css`:
  e.g. `--bp-row` (480px container), `--bp-phone` (540px), `--bp-maint` (640px),
  `--bp-nav` (768px), `--bp-split` (880px) — each with a documented purpose.
  (Container queries: `@container (max-width: …)` cannot use custom-media; keep
  the literal but reference the shared value in a comment.)
- Rewrite the existing `@media` literals to reference the tokens.
- Add matching values to `theme.breakpoints` so viewport-aware components
  (Workstream K) read a real source of truth, not a hardcoded `880`.
- **Verify visual parity** — pure refactor, no layout change.

### B. Touch targets (phone-critical)

- One `global.css` rule set: at `--bp-phone`, promote actionable icon buttons in
  list/toolbar contexts to the existing 44px `data-size="lg"` footprint
  (`.app-row`/`.lib-row-actions`/`.jobs-list-row`/active-job/maintenance icon
  buttons). Keep ≥8px between adjacent targets.
- `MobileMenuButton` 40 → 44px **always** (it is the only phone nav affordance);
  honors the existing CSS comment that already claims 44px.
- `.mob-drawer-close` 32 → 44px at phone width.
- `MaintenancePanel` raw `✕` `ActionIcon` → `.icon-btn` (also Workstream K) so
  cancel is a real 44px target distinct from row-select.
- Audit `SortDirToggle`, `ListPagination` controls; bump to 44px at phone width.

### C. Form / toolbar reflow (phone-critical)

- `nowrap → wrap` on primary-action Groups so the button drops full-width under
  the input at ~360px: `SubmitForm` URL+Download (the app's main action),
  `DirectoryPicker` create-folder, `UpdateLxcCard` banner Groups.
- Replace fixed `w={…}` with flex / `miw` so each control goes full-width
  one-per-row on phones:
  - `LogsPanel` — **currently has zero responsive CSS**; 140+200+260 inputs.
  - `RecentList` / `ListToolbar` — 140+150+toggle+180 search.
  - `TargetRow` expanded controls — 170+180+160.
  - `UpdateLxcCard` `PreviewRefControl`.
- `InlineConfirm` — allow wrap so a long destructive message + buttons stack
  instead of pinning two tiny buttons to the right.

### D. Scroll traps & overflow

- `ProgressCard` chapter list `ScrollArea h={220}` → grow / viewport-relative cap
  at `--bp-phone` so a swipe scrolls the page, not a 5-row inner window.
- `LibraryBackup` import-error list → cap in a `ScrollArea` (mirror
  `UpdateLxcCard`'s changelog) so a bad import can't grow multi-screen.
- `MaintenanceLog` phone expand-toggle → scroll the expanded box into view.

### E. Safe-area

- Mirror the drawer's `env(safe-area-inset-*)` onto `.app-shell-header`
  (padding-top) and `.app-shell-body` / `.app-footnote` (padding-bottom).

### F. Reduced motion

- One `@media (prefers-reduced-motion: reduce)` block neutralizing
  `app-shimmer`, `app-pulse`, the drawer slide transform, and hover/colour
  transitions.

### G. Copy — status & vocabulary consistency

- `MaintenancePanel` status pill → `jobStatusLabel()` (reads "Completed", not
  raw `completed`). Add a small maint-specific label map if statuses differ.
- `ProgressCard` transient labels: `packing…` → `processing…`,
  `preparing…` → `fetching…`; append the `chapters` unit in the packing branch.
- Spell the unit `chapters` (not `ch.`) in `RunningJobsPanel` and `RecentRow` to
  match `ProgressCard`.
- `HealthBadge` — render `checking` during load so the pill always reads
  "backend · <status>".
- `ProgressCard` chapter placeholder `(root)` → `(untitled)`.
- **Noun sweep:** `Add a gallery` → `Add a series`; drawer `Maintain` →
  `Maintenance`; reconcile `TargetRow` tooltip ("Remove from library") vs toast
  ("Series removed"); drawer kicker `Navigate` (verb) → a short uppercase noun;
  `ConfigPanel` bare "config" as a noun. Keep `Gallery URL` on the input only.
- Sentence-case stray system strings: `url is required` → `Enter a gallery URL.`;
  `path is required` → `Enter a folder name.`; `LibraryBackup` `Done.` /
  "entries had problems" / "Imported N, updated M" → full sentences naming the
  object.

### H. Copy — jargon (plain-language, term in parens)

- `SubmitForm`: explain `ComicInfo Manga=YesAndRightToLeft`, define `cadence`,
  clarify that tag replacement is **per-series** not global.
- `ConfigPanel`: give the Jinja2 variable list a working example; replace casual
  "Bumping this"; state the restart requirement explicitly (not just "Applied at
  startup").
- `MaintenancePanel`: rewrite `fan out`, `idempotent`, and the stale
  `(rename, regenerate, rebuild)` parenthetical that no longer matches the
  buttons.
- `RebuildLibraryCard`: "Plan to be offline for several hours" → make clear the
  *service* is unavailable, not the user.

### I. Narrow-row crowding

- `RecentRow` chapter chip — drop `whiteSpace:nowrap` (or shorten) so
  "12/40 chapters · 3 failed" can wrap instead of crowding the pill at ≤480px.
- `RunningJobsPanel` — mirror `RecentRow`'s URL subtitle so the two near-identical
  stacked row types show consistent information density.

### J. Maintenance result cell (expandable)

- The clamped `JSON.stringify` cell becomes tap-to-expand inline (collapsed by
  default) so phone users can read the full payload. No backend coupling.

### K. Off-system one-offs + viewport-aware

- `UpdateLxcCard` raw `grape` Mantine `Badge` → five-tone `.pill`/tone.
- `MaintenancePanel` raw `✕` `ActionIcon` → `.icon-btn` (shared with B).
- `JobStepper` — simplify the phone decorative-only icon row that duplicates the
  "Step N of 6" caption.
- **`JobsTabBody` viewport-aware** — currently a selection forces `.jobs-grid`,
  which only collapses at 880px via CSS. Use `useMediaQuery` against
  `theme.breakpoints` so phones never enter the two-column grid regardless of
  selection. The "couple of viewport-aware components" refactor piece.

## Testing & verification

- **Unit tests** (`*.test.tsx`) updated/added where *logic* changes:
  status/label mappings (G), viewport-aware rendering (K, mocking
  `useMediaQuery`), expandable result cell (J), `HealthBadge` loading state.
  Update `*.stories.tsx` where they already exist.
- **CSS-only changes** (B touch-target rules, C reflow, E safe-area,
  F reduced-motion) cannot be meaningfully unit-tested — these get **manual
  visual verification**: run the app and check **phone width + both colour
  schemes** before claiming done.
- `mise run check` (lint + typecheck + test) green is the completion gate.

## Out of scope

- Backend changes (the expandable result cell renders existing payloads).
- New features or new screens.
- Replacing the hand-rolled CSS responsive system with Mantine responsive props
  wholesale (only the specific `JobsTabBody` grid-entry becomes viewport-aware).
- Restyling beyond the audited findings; no new colours, gradients, or imagery.

## Risks

- CSS-only changes need real visual verification (the audit was static) — a
  rendered check at phone width in both schemes is part of "done".
- Several existing rules target Mantine-internal classnames
  (`.mantine-Stepper-stepLabel`, `.mantine-Tabs-list`); touch them carefully to
  avoid Mantine-upgrade brittleness.
- The noun sweep (G) touches many files; keep it mechanical and grep-verified to
  avoid missing a surface.
