# Copy + Responsive UX Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine copy and responsive layout across the gallery-dl-webui frontend — desktop, phones especially — against the existing editorial design system, with no new aesthetic.

**Architecture:** Four phases — **foundation** (centralize breakpoints behind `postcss-custom-media` tokens + `theme.breakpoints`), **structural** (touch targets, form/toolbar reflow, scroll traps, safe-area, reduced-motion), **copy** (status/vocabulary consistency + jargon), **polish** (narrow-row crowding, expandable result cell, off-system one-offs, viewport-aware Jobs layout). Most changes reuse existing `--app-*`/`--tone-*` tokens and `.icon-btn`/`.pill` utilities; the only new machinery is one PostCSS plugin and one viewport-aware component.

**Tech Stack:** React 19 + TypeScript, Mantine v9, TanStack Query, Vite (rolldown). Tests: vitest + React Testing Library + Playwright (e2e). Lint: biome. Run everything through `mise` (e.g. `mise run test:frontend`, `mise run lint`, `mise run typecheck`, `mise run check`).

## Sequencing (hard ordering constraints)

1. **Phase 1 (A) lands first.** Workstreams B/C/D/J write `@media (--bp-phone)` / `(--bp-maint)`; those tokens only resolve once A installs `postcss-custom-media` and declares them. Build breaks if a token is used before A merges.
2. **A's three CSS-foundation edits (dep + config + global.css rewrite) land in ONE commit** so the build never sees a token without its resolver.
3. **G before I.** Both edit `RecentRow.tsx`/`RecentRow.test.tsx`; G renames the `ch.`→`chapters` unit, I removes the inline nowrap and asserts the post-rename string.
4. **B before K.** B's `.maint-jobs-table .icon-btn` phone rule promotes K's converted cancel button to 44px; B's rule is a harmless no-op until K lands.
5. **A before K.** K's `JobsTabBody` reads `theme.breakpoints.split` (defined in A2).
6. Within `MaintenancePanel.tsx`, G (status label), J (result cell + `MaintResultCell`), and K (✕→`.icon-btn`) edit **disjoint regions** — any order, but re-locate anchors when applying later edits.

---

# Phase 1 — Foundation (Workstream A)

### Task A1: Centralize breakpoints behind postcss-custom-media (single commit)

**Files:**
- Modify: `frontend/package.json` (devDependencies)
- Create: `frontend/postcss.config.cjs`
- Modify: `frontend/src/styles/global.css` (token block + 9 literal rewrites + 480 container comment)

- [ ] **Step 1: Install the plugin**

Run from `frontend/`: `pnpm add -D postcss-custom-media`
Expected: resolves `^11.x`, updates `package.json` + `pnpm-lock.yaml`, exit 0. Let the lockfile own the exact version.

- [ ] **Step 2: Create `frontend/postcss.config.cjs`**

```js
// PostCSS config — auto-discovered by Vite at the frontend root.
//
// The single plugin here, postcss-custom-media, resolves the named
// `@custom-media --bp-*` tokens declared at the top of src/styles/global.css
// into concrete `@media (max-width: …)` rules at build time. This lets every
// breakpoint live in one definition block instead of scattered literals.
//
// Note: `@container` queries cannot read custom-media (the spec only resolves
// them inside `@media`), so the 480px `.app-row` container query in global.css
// stays a literal — see the cross-reference comment there.
//
// CommonJS (.cjs) because package.json sets "type": "module"; PostCSS loads
// its config via require(), so an ESM .js here would fail to load.
module.exports = {
  plugins: {
    "postcss-custom-media": {},
  },
};
```

- [ ] **Step 3: Add the token block after the `@import` at the top of `global.css`**

Insert immediately after the font `@import` (after line 4):

```css
/* Responsive breakpoint tokens — single source of truth for every `@media`
   query in this file. Resolved at build time by postcss-custom-media (see
   ../../postcss.config.cjs). Kept in sync with `theme.breakpoints` in
   ../theme.ts (same px values, expressed there in em for Mantine's JS API).
   Each token is max-width: the rule applies at that width and below.

     --bp-phone  540px  phone gutters / header / lib + active-job declutter
     --bp-maint  640px  maintenance table → stacked cards, log expand toggle
     --bp-nav    768px  top tabs → slide-in drawer navigation
     --bp-split  880px  Jobs master-detail grid → single column

   Container queries can't read custom-media (the spec only resolves tokens
   inside `@media`), so the 480px `.app-row` `@container` query below stays a
   literal — it is the row-local sibling of --bp-phone, documented inline. */
@custom-media --bp-phone (max-width: 540px);
@custom-media --bp-maint (max-width: 640px);
@custom-media --bp-nav (max-width: 768px);
@custom-media --bp-split (max-width: 880px);
```

- [ ] **Step 4: Rewrite the 9 literal `@media` preludes to tokens**

Each is an exact find→replace (verify uniqueness by line — `540px` appears 5×):
- line 156 `@media (max-width: 540px) {` → `@media (--bp-phone) {`
- line 247 `@media (max-width: 540px) {` → `@media (--bp-phone) {`
- line 740 `@media (max-width: 540px) {` → `@media (--bp-phone) {`
- line 1174 `@media (max-width: 540px) {` → `@media (--bp-phone) {`
- line 1202 `@media (max-width: 540px) {` → `@media (--bp-phone) {`
- line 807 `@media (max-width: 880px) {` → `@media (--bp-split) {`
- line 863 `@media (max-width: 640px) {` → `@media (--bp-maint) {`
- line 942 `@media (max-width: 640px) {` → `@media (--bp-maint) {`
- line 987 `@media (max-width: 768px) {` → `@media (--bp-nav) {`

**Do NOT touch** line 348 `@container (max-width: 480px) {` — it stays literal.

- [ ] **Step 5: Add the cross-reference comment on the 480px container query**

Current (the comment tail above the container query, ~line 347):
```css
   `order: 99` pushes the name behind the short meta chips when it wraps. */
@container (max-width: 480px) {
```
New:
```css
   `order: 99` pushes the name behind the short meta chips when it wraps.
   NOTE: 480px is a literal here on purpose — `@container` queries can't read
   the `@custom-media --bp-*` tokens (resolved only inside `@media`). This is
   the row-local companion to --bp-phone (540px); keep them moving together. */
@container (max-width: 480px) {
```

- [ ] **Step 6: Verify the build resolves tokens to identical literals**

Run from `frontend/`:
- `pnpm build` → exit 0; grep built `dist/` CSS: contains `540px`/`640px`/`768px`/`880px`, contains **no** `--bp-`.
- `mise run lint` → exit 0.
- Manual parity: at 430/540/600/700/850/1000px in light + dark, confirm header tag hide, lib-row wrap, maintenance stacked cards, tabs→drawer, and Jobs single-column flip at the **same** widths as before.

- [ ] **Step 7: Commit (all three files together)**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/postcss.config.cjs frontend/src/styles/global.css
git commit -m "refactor(css): centralize breakpoints behind postcss-custom-media tokens"
```

### Task A2: Add `theme.breakpoints` (keep Mantine defaults, add app tokens)

**Files:** Modify `frontend/src/theme.ts`

- [ ] **Step 1: Verify Container width dependency first**

Mantine v9 `<Container size="lg">` (App.tsx) may read `theme.breakpoints`. To eliminate any width regression, this task **keeps Mantine's default keys** and adds the app tokens alongside. After editing, confirm `<Container size="lg">` renders the same max-width (visual diff at desktop).

- [ ] **Step 2: Add the `breakpoints` map**

Current (inside `createTheme({...})`, after `colors: { amber, ink },`):
```ts
  black: "#1a160e",
  colors: { amber, ink },
```
New:
```ts
  black: "#1a160e",
  colors: { amber, ink },
  // JS-side source of truth for viewport-aware components (useMediaQuery).
  // Mantine's default keys are kept so Container/size lookups are unchanged;
  // the app tokens mirror the `@custom-media --bp-*` values in
  // styles/global.css (px → em at base 16). 480 is intentionally absent: it is
  // a row-local `@container` threshold, not a viewport breakpoint.
  breakpoints: {
    xs: "36em",
    sm: "48em",
    md: "62em",
    lg: "75em",
    xl: "88em",
    phone: "33.75em", // 540px — --bp-phone
    maint: "40em", //    640px — --bp-maint
    nav: "48em", //      768px — --bp-nav
    split: "55em", //    880px — --bp-split
  },
```

- [ ] **Step 3: Verify + commit**

Run: `mise run typecheck` → exit 0 (Mantine types `breakpoints` as `Record<string,string>`). `mise run build` → exit 0. No component reads the new keys yet, so no visual change.
```bash
git add frontend/src/theme.ts
git commit -m "feat(theme): add breakpoints map mirroring CSS --bp-* tokens"
```

---

# Phase 2 — Structural (Workstreams B, C, D, E, F)

> All CSS in this phase uses the `--bp-*` tokens from A. Place each new phone rule **after** the rule it overrides so the specificity tie breaks on source order.

## Workstream B — Touch targets (44px at phone width only)

### Task B1: Promote list/toolbar icon buttons to 44px at phone width

**Files:** Modify `frontend/src/styles/global.css`

- [ ] **Step 1: Append after the `.icon-btn[disabled]` rule (after line 675)**

```css

/* Phones: desktop keeps its deliberately tight density, but on a touch
   screen the 26/32px icon buttons in list + toolbar rows are below the 44px
   tap-target floor and sit too close together. Promote every actionable
   .icon-btn in these contexts to the existing data-size="lg" footprint and
   keep >=8px between adjacent targets. Reuses the 44px variant rather than
   touching each component's data-size prop. */
@media (--bp-phone) {
  .app-row .icon-btn,
  .lib-row-actions .icon-btn,
  .jobs-list-row .icon-btn,
  .active-job-head-actions .icon-btn,
  .maint-jobs-table .icon-btn {
    width: 44px;
    height: 44px;
    border-radius: 10px;
  }
  .app-row .icon-btn svg,
  .lib-row-actions .icon-btn svg,
  .jobs-list-row .icon-btn svg,
  .active-job-head-actions .icon-btn svg,
  .maint-jobs-table .icon-btn svg {
    width: 18px;
    height: 18px;
  }
  .lib-row-actions,
  .active-job-head-actions {
    gap: 8px;
  }
}
```

- [ ] **Step 2: Verify** — `mise run dev`, narrow to 430px: RecentRow/TargetRow/active-job icon buttons render 44×44 with ≥8px gaps; >540px they stay 26/32px. `mise run lint` green. Both schemes. (The `.maint-jobs-table .icon-btn` scope is a no-op until K1; that's intended.)
- [ ] **Step 3: Commit** — `git commit -am "feat(css): 44px touch targets for list/toolbar icon buttons on phones"`

### Task B2: Hamburger `.mob-menu-btn` 40→44px (always)

**Files:** Modify `frontend/src/styles/global.css`

- [ ] **Step 1: Edit the `.mob-menu-btn` rule (lines 948-963)** — change `width: 40px; height: 40px;` to `width: 44px; height: 44px;` and update the comment to: `It is the only nav affordance on phones, so it always carries a full 44px touch target.` Leave `.mob-menu-btn svg { width: 20px; height: 20px; }` unchanged.
- [ ] **Step 2: Verify** — header hamburger is 44×44 at every width ≤768px. `mise run lint` green. `MobileMenuButton.tsx` needs no change (size lived only in CSS).
- [ ] **Step 3: Commit** — `git commit -am "fix(css): hamburger touch target 40->44px"`

### Task B3: Drawer close `.mob-drawer-close` 32→44px at phone width

**Files:** Modify `frontend/src/styles/global.css`

- [ ] **Step 1: Append after `.mob-drawer-close:focus-visible` (after line 1079)**

```css

/* Phones: the drawer is touch-only, so its close affordance gets the full
   44px target. */
@media (--bp-phone) {
  .mob-drawer-close {
    width: 44px;
    height: 44px;
    border-radius: 10px;
  }
}
```

- [ ] **Step 2: Verify** — open drawer ≤540px: close button 44×44; 541-768px stays 32px. `mise run lint` green.
- [ ] **Step 3: Commit** — `git commit -am "feat(css): 44px drawer close button on phones"`

### Task B4: SortDirToggle 44px at phone width

**Files:** Modify `frontend/src/components/SortDirToggle.tsx`, `frontend/src/styles/global.css`

- [ ] **Step 1: Add a stable class to the ActionIcon (SortDirToggle.tsx lines 23-28)** — add `className="sort-dir-toggle"` to the `<ActionIcon>` (keep `variant`, `size="lg"`, `onClick`, `aria-label`).
- [ ] **Step 2: Add the phone rule to `global.css`** (near the other toolbar/phone rules):

```css
/* Phones: the sort-direction toggle is a primary touch control. */
@media (--bp-phone) {
  .sort-dir-toggle {
    width: 44px;
    height: 44px;
    min-width: 44px;
    min-height: 44px;
  }
}
```

- [ ] **Step 3: Verify** — ≤540px the toggle is 44×44; desktop keeps Mantine `size="lg"` (~34px). `mise run lint` + `mise run typecheck` green.
- [ ] **Step 4: Commit** — `git commit -am "feat: 44px sort-direction toggle on phones"`

### Task B5: ListPagination 44px controls at phone width

**Files:** Modify `frontend/src/components/ListPagination.tsx`, `frontend/src/styles/global.css`

- [ ] **Step 1: Add `className="list-pagination"` to the wrapping `<Group>` (ListPagination.tsx lines 25-26).**
- [ ] **Step 2: Add the phone rule to `global.css`:**

```css
/* Phones: pagination page buttons become real touch targets. */
@media (--bp-phone) {
  .list-pagination .mantine-Pagination-control {
    min-width: 44px;
    height: 44px;
  }
}
```

- [ ] **Step 3: Verify** — ≤540px each page control ≥44px, no gutter overflow at 430px; desktop keeps `size="sm"`. `mise run lint` + `mise run typecheck` green.
- [ ] **Step 4: Commit** — `git commit -am "feat: 44px pagination controls on phones"`

## Workstream C — Form/toolbar reflow

> All edits are layout-only; existing `*.test.tsx` assert behaviour, not layout, so they stay green. Verify = visual at phone width + both schemes, then `mise run lint` + `mise run typecheck`.

### Task C1: SubmitForm URL+Download Group `nowrap`→`wrap`

**Files:** Modify `frontend/src/components/SubmitForm.tsx`

- [ ] **Step 1: Edit the primary-action Group (~lines 103-121)** — change `wrap="nowrap"`→`wrap="wrap"`; set the `TextInput` `style={{ flex: 1, minWidth: 220 }}`; give the `<Button>` `style={{ flexGrow: 1, minWidth: 140 }}`.
- [ ] **Step 2: Verify** — phone: input full row, Download full-width below; desktop unchanged. `SubmitForm.test.tsx` green.
- [ ] **Step 3: Commit** — `git commit -am "fix(submit-form): wrap URL+Download so the action reflows on phones"`

### Task C2: DirectoryPicker create-folder Group `nowrap`→`wrap`

**Files:** Modify `frontend/src/components/DirectoryPicker.tsx`

- [ ] **Step 1: Edit the create-folder Group (~lines 128-143)** — `wrap="nowrap"`→`wrap="wrap"`; `TextInput` `style={{ flex: 1, minWidth: 200 }}`; Create `<Button>` `style={{ flexGrow: 1 }}`. **Leave the picker Select+`+` Group (~line 92) as `wrap="nowrap"`** (the 44px `+` must hug the Select).
- [ ] **Step 2: Verify** — phone: name input full row, Create+Cancel below; desktop one row. Lint/typecheck green.
- [ ] **Step 3: Commit** — `git commit -am "fix(directory-picker): wrap create-folder controls on phones"`

### Task C3: LogsPanel filter toolbar — fixed widths → flex + phone CSS

**Files:** Modify `frontend/src/components/LogsPanel.tsx`, `frontend/src/styles/global.css`

- [ ] **Step 1: Edit the inner filter Group (LogsPanel.tsx ~lines 234-270)** — add `className="logs-filter-row"` to the inner `<Group>`; `NumberInput` `w={140}`→`miw={120}`; `Select` `w={200}`→`miw={180}`; `TextInput` `w={260}`→`style={{ flex: 1, minWidth: 200 }}`.
- [ ] **Step 2: Append to `global.css`** (LogsPanel had no responsive CSS):

```css
/* LogsPanel filter controls — stack one-per-row on phones (was fixed-width). */
@media (--bp-phone) {
  .logs-filter-row {
    width: 100%;
  }
  .logs-filter-row > * {
    flex: 1 1 100%;
    min-width: 0;
  }
}
```

- [ ] **Step 3: Verify** — phone: Lines/Level/Filter each full-width one-per-row; desktop: Filter grows. `LogsPanel.test.tsx` green. Lint/typecheck green.
- [ ] **Step 4: Commit** — `git commit -am "fix(logs-panel): stack filter controls one-per-row on phones"`

### Task C4: RecentList Status + Sort sub-Group → flex-basis

**Files:** Modify `frontend/src/components/RecentList.tsx`

- [ ] **Step 1: Edit the toolbar children (~lines 189-217)** — Status `Select`: `w={140}`→`miw={130}` + `style={{ flex: "1 1 130px" }}`. Sort sub-`Group`: add `style={{ flex: "1 1 180px" }}` (keep `wrap="nowrap"`). Sort-by `Select`: `w={150}`→`style={{ flex: 1 }}`. (Parent `ListToolbar` is already `wrap="wrap"`.)
- [ ] **Step 2: Verify** — phone: search row, then Status and Sort-by each take a full row; SortDirToggle stays pinned to its select; desktop unchanged. Lint/typecheck green.
- [ ] **Step 3: Commit** — `git commit -am "fix(recent-list): reflow status + sort toolbar on phones"`

### Task C5: TargetRow expanded controls — fixed widths → flex

**Files:** Modify `frontend/src/components/TargetRow.tsx`

- [ ] **Step 1: Edit the expanded `.lib-row-body` Group (~lines 267-330)** — Poll-every `TextInput`: `w={170}`→`miw={150}` + `style={{ flex: "1 1 170px" }}`. Reading-direction `Select`: `w={180}`→`miw={150}` + `style={{ flex: "1 1 180px" }}`. Series-status `Select`: `w={160}`→`miw={150}` + `style={{ flex: "1 1 160px" }}`. Leave the Watch Switch auto-width.
- [ ] **Step 2: Verify** — phone: expand a Library row, the three fields each take a full row; desktop multi-column wrap near old widths. Don't collapse below the label at ~320px. Lint/typecheck green.
- [ ] **Step 3: Commit** — `git commit -am "fix(target-row): reflow expanded controls on phones"`

### Task C6: UpdateLxcCard PreviewRefControl tag Select → flex

**Files:** Modify `frontend/src/components/UpdateLxcCard.tsx`

- [ ] **Step 1: Edit the PreviewRefControl Group (~lines 476-514)** — `TextInput` `style={{ flex: 1, minWidth: 220 }}`→`style={{ flex: "1 1 220px", minWidth: 200 }}`; version-tag `Select` `w={180}`→`miw={150}` + `style={{ flex: "1 1 180px" }}`.
- [ ] **Step 2: Verify** — phone: Track-ref input, tag Select, Save/Reset each reflow to their own row; desktop input grows with ~180px Select beside it. Lint/typecheck green.
- [ ] **Step 3: Commit** — `git commit -am "fix(update-lxc): reflow preview-ref controls on phones"`

### Task C7: UpdateLxcCard banner buttons full-width on phones

**Files:** Modify `frontend/src/components/UpdateLxcCard.tsx`

- [ ] **Step 1: Edit the `!armed`/armed Groups (~lines 177-205)** — `!armed`: `<Group>`→`<Group wrap="wrap">` and give the trigger Button `style={{ flexGrow: 1, minWidth: 140 }}`. Armed: give "Yes, update now" `style={{ flexGrow: 1, minWidth: 160 }}` and Cancel `style={{ flexGrow: 1, minWidth: 100 }}`. Leave the leading `<Text>` as `style={{ flex: 1, minWidth: 200 }}`.
- [ ] **Step 2: Verify** — phone: "Update LXC…" fills its row; armed message stacks above the two buttons; desktop natural-sized. Lint/typecheck green.
- [ ] **Step 3: Commit** — `git commit -am "fix(update-lxc): full-width banner buttons on phones"`

### Task C8: InlineConfirm wraps on phones

**Files:** Modify `frontend/src/components/InlineConfirm.tsx`, `frontend/src/styles/global.css`

- [ ] **Step 1: Add `className="confirm-actions"` to the buttons `<Group>` (InlineConfirm.tsx lines 36-37).**
- [ ] **Step 2: Append to `global.css`:**

```css
/* InlineConfirm — stack message above the buttons on phones instead of
   squeezing two tiny buttons to the right. */
@media (--bp-phone) {
  .confirm-strip {
    flex-wrap: wrap;
    align-items: flex-start;
  }
  .confirm-strip .confirm-msg {
    flex: 1 1 100%;
  }
  .confirm-strip .confirm-actions {
    margin-left: auto;
  }
}
```

- [ ] **Step 3: Verify** — phone: a long confirm message (TargetRow remove) wraps with Cancel/Remove on the row below; desktop one line. Lint/typecheck green.
- [ ] **Step 4: Commit** — `git commit -am "fix(inline-confirm): wrap message above buttons on phones"`

## Workstream D — Scroll traps & overflow

### Task D1: ProgressCard chapter list — grow + viewport cap (no inner scroll trap)

**Files:** Modify `frontend/src/styles/global.css`

- [ ] **Step 1: Append inside the `@media (--bp-phone)` active-job block (before its closing `}`, ~line 1239)**

```css

  /* The chapter list is a Mantine ScrollArea pinned at h=220 in JS. On a phone
     a fixed 220px inner window steals the swipe: a vertical drag scrolls five
     rows instead of the page. Let the list grow with the content and cap it
     viewport-relative so a long manifest still can't run multi-screen. */
  .active-job-chapters .mantine-ScrollArea-root,
  .active-job-chapters .mantine-ScrollArea-viewport {
    height: auto !important;
    max-height: 60vh;
  }
```

- [ ] **Step 2: Verify** — phone ≤540px: a swipe over the chapter list scrolls the page; long manifest caps ~60vh; desktop keeps the 220px box. `mise run lint` + `mise run typecheck` green. (`!important` is required to beat Mantine's inline `h` height. This targets Mantine-internal classnames — re-check on Mantine upgrade.)
- [ ] **Step 3: Commit** — `git commit -am "fix(progress-card): let chapter list scroll the page on phones"`

### Task D2: LibraryBackup — cap import-error list in a ScrollArea

**Files:** Modify `frontend/src/components/LibraryBackup.tsx`; Create `frontend/src/components/LibraryBackup.test.tsx`

- [ ] **Step 1: Write the failing test** (`LibraryBackup.test.tsx`)

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";

const importLibrary = vi.fn();
vi.mock("../lib/libraryBackup", () => ({
  exportLibrary: vi.fn(),
  importLibrary: (...args: unknown[]) => importLibrary(...args),
}));
vi.mock("../lib/invalidate", () => ({
  useDataInvalidators: () => ({ targets: vi.fn() }),
}));

import { LibraryBackup } from "./LibraryBackup";

afterEach(() => {
  vi.clearAllMocks();
});

describe("LibraryBackup import errors", () => {
  it("renders every import error inside a capped scroll container", async () => {
    const errors = Array.from({ length: 40 }, (_, i) => `row ${i} failed: bad url`);
    importLibrary.mockResolvedValue({ imported: 1, updated: 0, errors });

    const { container } = renderWithProviders(<LibraryBackup />);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "lib.yaml", { type: "text/yaml" }));

    await waitFor(() => expect(screen.getByText(/40 entries had problems/i)).toBeInTheDocument());

    expect(screen.getByText("row 0 failed: bad url")).toBeInTheDocument();
    expect(screen.getByText("row 39 failed: bad url")).toBeInTheDocument();
    expect(container.querySelector(".mantine-ScrollArea-viewport")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run it — expect FAIL** (`.mantine-ScrollArea-viewport` not present): `cd frontend && pnpm vitest run src/components/LibraryBackup.test.tsx`
- [ ] **Step 3: Implement** — in `LibraryBackup.tsx`, add `ScrollArea` to the `@mantine/core` import (keep alphabetical: `List, ScrollArea, Stack`), and wrap the error `<List>` (the `else` branch, ~lines 75-83):

```tsx
              {/* Mirror UpdateLxcCard's ChangelogList: grow with the error count
                  but cap viewport-relative so a 500-line bad import stays a
                  scrollable panel instead of pushing the whole page down. */}
              <ScrollArea.Autosize mah="min(40vh, 320px)" type="auto">
                <List size="sm" withPadding>
                  {importResult.errors.map((e) => (
                    <List.Item key={e}>{e}</List.Item>
                  ))}
                </List>
              </ScrollArea.Autosize>
```

- [ ] **Step 4: Run it — expect PASS.** Then `mise run lint` + `mise run typecheck` green.
- [ ] **Step 5: Commit** — `git commit -am "fix(library-backup): cap import-error list in a scroll area"`

### Task D3: MaintenanceLog — scroll expanded box into view

**Files:** Modify `frontend/src/components/MaintenanceLog.tsx`; Create `frontend/src/components/MaintenanceLog.test.tsx`

- [ ] **Step 1: Write the failing test** (`MaintenanceLog.test.tsx`)

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { MaintenanceLog } from "./MaintenanceLog";

const PROGRESS = { status: "running", done: 2, total: 4, lines: ["line one", "line two"] };

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("MaintenanceLog expand", () => {
  it("scrolls the log box into view when expanded", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress")) return jsonResponse(PROGRESS);
      return jsonResponse({});
    });

    renderWithProviders(<MaintenanceLog jobId={1} startedAt={null} />);

    const toggle = await screen.findByRole("button", { name: /expand job log/i });
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();

    await userEvent.click(toggle);

    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ block: "nearest" }),
    );
  });
});
```

- [ ] **Step 2: Run it — expect FAIL** (`scrollIntoView` never called): `cd frontend && pnpm vitest run src/components/MaintenanceLog.test.tsx`
- [ ] **Step 3: Implement** — in `MaintenanceLog.tsx`: change the react import (line 12) to `import { useEffect, useRef, useState } from "react";`; after the `expanded` state (line 43) add:

```tsx
  // When the user taps "expand" the box jumps to 70vh; on a phone the new top
  // edge can land above the fold. Pull the freshly-expanded box into view.
  const logBoxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (expanded) {
      logBoxRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [expanded]);
```
and add `ref={logBoxRef}` to the bordered `<Box>` (~lines 100-107) that wraps the `<ScrollArea h={expanded ? "70vh" : 240} …>`.

- [ ] **Step 4: Run it — expect PASS.** Then `mise run lint` + `mise run typecheck` green.
- [ ] **Step 5: Commit** — `git commit -am "fix(maintenance-log): scroll expanded log into view"`

## Workstream E — Safe-area insets

> All three are visual-only; `env(...)` resolves to 0 on conventional viewports (no-op). Verify with DevTools device emulation (notch + home indicator) at phone width; `mise run lint:frontend` green.

### Task E1: Top safe-area on `.app-shell-header`

**Files:** Modify `frontend/src/styles/global.css` (lines 71-77)

- [ ] **Step 1: Append inside the `.app-shell-header` block:**
```css
  /* Mirror the drawer's notch handling: keep the sticky header (and its fill)
     clear of the top safe-area inset on notched/edge-to-edge phones. */
  padding-top: env(safe-area-inset-top, 0);
```
- [ ] **Step 2: Verify** — notch emulation: header fill extends into the inset, content sits below it.
- [ ] **Step 3: Commit** — `git commit -am "fix(css): top safe-area inset on sticky header"`

### Task E2: Bottom safe-area on `.app-footnote` (the reliable carrier)

**Files:** Modify `frontend/src/styles/global.css` (lines 1278-1286)

- [ ] **Step 1: Change the footnote padding** from `padding: 1.5rem 0 0.5rem;` to:
```css
  /* Footnote is the last element in the scroll body, so it carries the bottom
     safe-area inset — mirrors `.mob-drawer`. */
  padding: 1.5rem 0 max(0.5rem, env(safe-area-inset-bottom, 0));
```
- [ ] **Step 2: Verify** — home-indicator emulation: the `gallery-dl · webui · vX` line clears the indicator.
- [ ] **Step 3: Commit** — `git commit -am "fix(css): bottom safe-area inset on footnote"`

### Task E3: Bottom safe-area guard on `.app-shell-body` (phone block)

**Files:** Modify `frontend/src/styles/global.css` (the `@media (--bp-phone) { .app-shell-body { … } }` block, lines 1174-1179)

- [ ] **Step 1: Append inside that `.app-shell-body` rule:**
```css
    /* Compose the inset with the phone-width vertical padding in case the
       footnote is short/absent. (Mantine's inline `py="xl"` shadows this
       padding-bottom, so .app-footnote is the guaranteed carrier — see E2.) */
    padding-bottom: max(var(--mantine-spacing-md), env(safe-area-inset-bottom, 0));
```
- [ ] **Step 2: Verify** — phone width + bottom inset: trailing content clears the indicator. (Known caveat: best-effort due to inline `py`; E2 is load-bearing.)
- [ ] **Step 3: Commit** — `git commit -am "fix(css): bottom safe-area guard on shell body at phone width"`

## Workstream F — Reduced-motion guard

### Task F1: prefers-reduced-motion block

**Files:** Modify `frontend/src/styles/global.css` (append at the very END of file, after line 1312)

- [ ] **Step 1: Append:**
```css

/* Reduced-motion guard. Viewers who ask the OS to minimise motion get the
   same layout with the movement removed: the skeleton shimmer (app-shimmer)
   and loading health dot (app-pulse) hold a static frame, the drawer snaps
   open/closed instead of sliding (the translateX position is preserved — only
   the transition is killed), and every hover/colour/transform transition
   collapses to near-instant. Keeping a 0.01ms duration rather than `none`
   lets transitionend/animationiteration handlers still fire. */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```
- [ ] **Step 2: Verify** — DevTools › Rendering › Emulate `prefers-reduced-motion: reduce`: skeletons + health dot stop animating, drawer opens without slide, hover shifts instant. `mise run lint` green.
- [ ] **Step 3: Commit** — `git commit -am "feat(css): respect prefers-reduced-motion"`

---

# Phase 3 — Copy (Workstreams G, H)

## Workstream G — Status & vocabulary consistency

> Two existing tests pin old copy and MUST change in lockstep: `SubmitForm.test.tsx:206` and `e2e/downloads.spec.ts:43` (G8). The `RecentRow.test.tsx:68` `"5 ch."` assertion changes in G4.

### Task G1: MaintenancePanel status pill → maintenance label map

**Files:** Modify `frontend/src/lib/maintenance.ts`, `frontend/src/components/MaintenancePanel.tsx`; update `frontend/src/components/MaintenancePanel.test.tsx`

- [ ] **Step 1: Write the failing test** — add to `MaintenancePanel.test.tsx`:

```tsx
  it("renders the maintenance status as a cased label, not the raw token", async () => {
    const nextId = { value: 2 };
    const jobs: Job[] = [
      {
        id: 1,
        kind: "rename_chapters",
        status: "completed",
        created_at: "2025-01-01T00:00:00",
        started_at: "2025-01-01T00:00:01",
        finished_at: "2025-01-01T00:00:02",
        result: { renamed: 1 },
        error: null,
      },
    ];
    const progress: Record<number, { status: string; total: number; done: number; lines: string[] }> = {
      1: { status: "completed", total: 5, done: 5, lines: ["done"] },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.queryByText("completed")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it — expect FAIL** (`completed` token rendered, no `Completed`).
- [ ] **Step 3: Implement** — append to `lib/maintenance.ts` after `KIND_LABEL`:

```ts
// Maintenance jobs share the download lifecycle vocabulary but not its
// meaning: a maintenance job that is `running` is not "Downloading", and a
// `pending` one is "Queued", not "Scheduled". So we route through a small
// maint-specific map instead of jobStatusLabel().
const MAINT_STATUS_LABELS: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function maintStatusLabel(status: string): string {
  return MAINT_STATUS_LABELS[status] ?? status;
}
```
Then in `MaintenancePanel.tsx` add `maintStatusLabel` to the `../lib/maintenance` import (line 24) and render the pill (lines 211-213) as:
```tsx
                          <Pill tone={statusTone(job.status)}>{maintStatusLabel(job.status)}</Pill>
```

- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green.
- [ ] **Step 5: Commit** — `git commit -am "fix(maintenance): label status pill instead of raw backend token"`

### Task G2: ProgressCard transient labels + chapters unit + (untitled)

**Files:** Modify `frontend/src/components/ProgressCard.tsx`; update `frontend/src/components/ProgressCard.test.tsx`

- [ ] **Step 1: Write the failing tests** — add to `ProgressCard.test.tsx`:

```tsx
  it("shows 'fetching…' before the manifest is ready", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({
          status: "running",
          files_expected: null,
          files_present: 0,
          chapters_discovered: null,
          chapters_needed: null,
          chapters_downloaded: 0,
          chapters_failed: 0,
          chapters_skipped: 0,
          chapters: [],
        });
      return jsonResponse({});
    });
    renderWithProviders(<ProgressCard jobId={2} status="running" startedAt={null} />);
    expect(await screen.findByText("fetching…")).toBeInTheDocument();
  });

  it("labels a nameless chapter as (untitled)", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({
          status: "completed",
          files_expected: 1,
          files_present: 1,
          chapters_discovered: 1,
          chapters_needed: 1,
          chapters_downloaded: 1,
          chapters_failed: 0,
          chapters_skipped: 0,
          chapters: [
            { name: "", files_total: 1, files_present: 1, stage: "downloaded", status: "downloaded", pages: 1, title: null, date: null, error: null },
          ],
        });
      return jsonResponse({});
    });
    renderWithProviders(<ProgressCard jobId={3} status="completed" startedAt={null} />);
    expect(await screen.findByText("(untitled)")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run — expect FAIL** (`preparing…`/`(root)` still rendered).
- [ ] **Step 3: Implement** — `ProgressCard.tsx` rightLabel block (lines 97-102):
```tsx
  let rightLabel: string;
  if (!manifestReady) rightLabel = "fetching…";
  else if (packing)
    rightLabel = `processing… · ${settledChapters} / ${totalChapters} chapters`;
  else if (eta.kind === "eta") {
    rightLabel = `~${formatEta(eta.remainingMs)} · ${settledChapters} / ${totalChapters} chapters`;
  } else rightLabel = `${settledChapters} / ${totalChapters} chapters`;
```
and line 145: `const label = ch.name || "(untitled)";`

- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green.
- [ ] **Step 5: Commit** — `git commit -am "fix(progress-card): align transient labels to lifecycle + (untitled)"`

### Task G3: RunningJobsPanel spells "chapters"

**Files:** Modify `frontend/src/components/RunningJobsPanel.tsx`; Create `frontend/src/components/RunningJobsPanel.test.tsx`

> NOTE: this test file is also created in I2 (URL subtitle). If I2 has not run, create the file here; otherwise append this `describe`. Land G before I so the file/order is coherent.

- [ ] **Step 1: Write the failing test** (`RunningJobsPanel.test.tsx`)

```tsx
import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { RunningJobsPanel } from "./RunningJobsPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RunningJobsPanel progress label", () => {
  it("spells the chapters unit", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/api/downloads"))
        return jsonResponse([
          {
            id: 7, url: "https://example/x", name: "Example", extractor: "fake",
            status: "running", created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:01Z",
            finished_at: null, exit_code: null, files_downloaded: 0, files_expected: null,
            chapters_total: 40, chapters_discovered: 40, chapters_failed: 0, error: null,
            postprocess_status: null, postprocess_chapters_packed: 12, postprocess_error: null,
            output_dir: null, target_id: null,
          },
        ]);
      return jsonResponse({});
    });

    renderWithProviders(<RunningJobsPanel onSelect={() => {}} selectedId={null} />);

    await waitFor(() => expect(screen.getByText("12/40 chapters")).toBeInTheDocument());
    expect(screen.queryByText(/ ch\./)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (`12/40 ch.` rendered).
- [ ] **Step 3: Implement** — `RunningJobsPanel.tsx` `progressLabel` (lines 12-24): change the two `ch.` literals to `chapters` (`` `${packed}/${total} chapters` `` and `` `${total} chapters` ``).
- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green.
- [ ] **Step 5: Commit** — `git commit -am "fix(running-jobs): spell the chapters unit"`

### Task G4: RecentRow spells "chapters"

**Files:** Modify `frontend/src/components/RecentRow.tsx`; update `frontend/src/components/RecentRow.test.tsx`

- [ ] **Step 1: Update the existing assertion** — `RecentRow.test.tsx:68`: `screen.getByText("5 ch.")` → `screen.getByText("5 chapters")`.
- [ ] **Step 2: Run — expect FAIL** (still renders `5 ch.`).
- [ ] **Step 3: Implement** — `RecentRow.tsx` `chapterCountLabel` (lines 7-14): change both `ch.` literals to `chapters`.
- [ ] **Step 4: Run — expect PASS** (`RecentRow.test.tsx`). Lint/typecheck green.
- [ ] **Step 5: Commit** — `git commit -am "fix(recent-row): spell the chapters unit"`

### Task G5: HealthBadge renders "checking" during load

**Files:** Modify `frontend/src/components/HealthBadge.tsx`; Create `frontend/src/components/HealthBadge.test.tsx`

- [ ] **Step 1: Write the failing tests** (`HealthBadge.test.tsx`)

```tsx
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { HealthBadge } from "./HealthBadge";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HealthBadge", () => {
  it("reads 'checking' while the health query is loading", () => {
    mockFetch(() => new Promise<Response>(() => {}));
    renderWithProviders(<HealthBadge />);
    expect(screen.getByText("checking")).toBeInTheDocument();
  });

  it("reads the backend status once loaded", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse({});
    });
    renderWithProviders(<HealthBadge />);
    expect(await screen.findByText("ok")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (no `checking` during load).
- [ ] **Step 3: Implement** — `HealthBadge.tsx`: drop `isLoading` from the destructure (line 11 → `const { data, error } = useQuery(getHealthOptions());`) and render the separator/label unconditionally (lines 23-32):
```tsx
      <span>·</span>
      <span>{label}</span>
```
(`label` already defaults to `"checking"` at line 14.)

- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green. (e2e health check still finds `ok` post-load.)
- [ ] **Step 5: Commit** — `git commit -am "fix(health-badge): show 'checking' during load"`

### Task G6: SubmitForm heading "Add a gallery" → "Add a series" (copy)

**Files:** Modify `frontend/src/components/SubmitForm.tsx` (line 101)

- [ ] **Step 1: Edit** — `<Title order={3}>Add a gallery</Title>` → `<Title order={3}>Add a series</Title>`. **Leave the "Gallery URL" input label (line 106) untouched.**
- [ ] **Step 2: Verify** — heading reads "Add a series". `mise run lint` clean (no test asserts the heading).
- [ ] **Step 3: Commit** — `git commit -am "copy(submit-form): 'Add a series'"`

### Task G7: MobileNavDrawer "Maintain"→"Maintenance", "Navigate"→"Sections" (copy)

**Files:** Modify `frontend/src/components/MobileNavDrawer.tsx`

- [ ] **Step 1: Edit** — line 11 item label `"Maintain"` → `"Maintenance"`; line 61 drawer title `<span className="mob-drawer-title">Navigate</span>` → `Sections`. (Leave the foot `archive` tag.)
- [ ] **Step 2: Verify** — drawer item matches desktop tab ("Maintenance"); title is the noun "Sections". `mise run lint` clean.
- [ ] **Step 3: Commit** — `git commit -am "copy(drawer): align 'Maintenance' + noun kicker"`

### Task G8: SubmitForm blank-URL error → sentence case (logic — e2e + unit)

**Files:** Modify `frontend/src/components/SubmitForm.tsx`; update `frontend/src/components/SubmitForm.test.tsx`, `frontend/e2e/downloads.spec.ts`

- [ ] **Step 1: Update both assertions** — `SubmitForm.test.tsx:206` `/url is required/i` → `/enter a gallery url\./i`; `e2e/downloads.spec.ts:43` `/url is required/i` → `/enter a gallery url\./i`.
- [ ] **Step 2: Run unit — expect FAIL**: `cd frontend && pnpm vitest run src/components/SubmitForm.test.tsx`.
- [ ] **Step 3: Implement** — `SubmitForm.tsx:80`: `setSubmitError("url is required")` → `setSubmitError("Enter a gallery URL.")`.
- [ ] **Step 4: Run — expect PASS** (unit). `mise run lint` + `mise run typecheck` green. (Run e2e if available in the environment.)
- [ ] **Step 5: Commit** — `git commit -am "copy(submit-form): sentence-case blank-URL error"`

### Task G9: DirectoryPicker blank-folder error → sentence case (logic)

**Files:** Modify `frontend/src/components/DirectoryPicker.tsx`; Create `frontend/src/components/DirectoryPicker.test.tsx`

- [ ] **Step 1: Write the failing test** (`DirectoryPicker.test.tsx`)

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { findCall, jsonResponse, methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { DirectoryPicker } from "./DirectoryPicker";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DirectoryPicker create validation", () => {
  it("shows a sentence-case error on blank folder name and skips the request", async () => {
    const spy = mockFetch(async (input) => {
      if (urlOf(input).includes("/api/output-dirs")) return jsonResponse([]);
      return jsonResponse({});
    });

    renderWithProviders(
      <DirectoryPicker label="Output directory" value={null} onChange={() => {}} enabled />,
    );

    await userEvent.click(screen.getByRole("button", { name: /create folder/i }));
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText(/enter a folder name\./i)).toBeInTheDocument();
    expect(findCall(spy, (i, init) => methodOf(i, init) === "POST")).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — `DirectoryPicker.tsx:83`: `setCreateError("path is required")` → `setCreateError("Enter a folder name.")`.
- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green.
- [ ] **Step 5: Commit** — `git commit -am "copy(directory-picker): sentence-case blank-folder error"`

### Task G10: TargetRow tooltip/toast reconcile to "series" (copy)

**Files:** Modify `frontend/src/components/TargetRow.tsx`

- [ ] **Step 1: Edit** — toast error title (lines 89-98) `"Delete failed"` → `"Remove failed"`; tooltip (line 214) `"Remove from library"` → `"Remove series"`. (Keep success toast `"Series removed"` and the `aria-label="Delete target {id}"` automation hook.)
- [ ] **Step 2: Verify** — tooltip "Remove series", toasts "Series removed"/"Remove failed". `mise run lint` clean.
- [ ] **Step 3: Commit** — `git commit -am "copy(target-row): reconcile remove verb + series noun"`

### Task G11: ConfigPanel "Loading config…" → "Loading configuration…" (copy)

**Files:** Modify `frontend/src/components/ConfigPanel.tsx` (line 122)

- [ ] **Step 1: Edit** — `<Text>Loading config…</Text>` → `<Text>Loading configuration…</Text>`. (Leave the `Config` tab label and lowercase mono kickers.)
- [ ] **Step 2: Verify** — loading reads "Loading configuration…". `mise run lint` + `mise run test` clean.
- [ ] **Step 3: Commit** — `git commit -am "copy(config): spell out 'configuration' in loading state"`

### Task G12: LibraryBackup import-result strings → sentence case naming "series" (copy)

**Files:** Modify `frontend/src/components/LibraryBackup.tsx` (lines 67-86)

- [ ] **Step 1: Edit** — title → `` `Imported ${importResult.imported} series, updated ${importResult.updated}.` ``; success body `"Done."` → `"Library imported."`; error lead `"{n} entries had problems:"` → `"{n} series could not be imported:"`. (Keep the `<List>`/`ScrollArea.Autosize` from D2.)
- [ ] **Step 2: Verify** — clean import: "Imported N series, updated M." + "Library imported."; with errors: "K series could not be imported:". `mise run lint` + `mise run test` clean.
- [ ] **Step 3: Commit** — `git commit -am "copy(library-backup): sentence-case import results naming series"`

## Workstream H — Jargon (plain-language, term in parens)

> All eight are pure copy/JSX-description edits (no logic). Verify each: `mise run lint` + `mise run typecheck` green + visual. Grep the test dir for the old phrases before committing (none currently assert them).

### Task H1: SubmitForm — explain ComicInfo enum

**Files:** `frontend/src/components/SubmitForm.tsx` (Reading-direction Select description, ~lines 161-163)
- [ ] **Step 1:** `description="RTL becomes ComicInfo Manga=YesAndRightToLeft."` → `description="Right-to-left tells the reader to page backwards (written into ComicInfo.xml as Manga=YesAndRightToLeft)."`
- [ ] **Step 2: Verify + Step 3: Commit** — `git commit -am "copy(submit-form): plain-language reading-direction help"`

### Task H2: SubmitForm — define "cadence"

**Files:** `frontend/src/components/SubmitForm.tsx` (Watch Checkbox description, ~lines 175-177)
- [ ] **Step 1:** `description="Re-poll this gallery on the default cadence for new chapters."` → `description="Check for new chapters on a repeating schedule (the default cadence set in Config)."`
- [ ] **Step 2: Verify + Step 3: Commit** — `git commit -am "copy(submit-form): define cadence on Watch"`

### Task H3: SubmitForm — clarify tag replacement is per-series

**Files:** `frontend/src/components/SubmitForm.tsx` (TagsInput description, ~lines 151-160)
- [ ] **Step 1:** `description="Applied to series.json + ComicInfo. Existing tags are replaced on every submit."` → `description="Written into this series' metadata (series.json + ComicInfo.xml). Submitting again replaces this series' tags only — other series are untouched."`
- [ ] **Step 2: Verify + Step 3: Commit** — `git commit -am "copy(submit-form): clarify tag replacement is per-series"`

### Task H4: ConfigPanel — Jinja2 template example

**Files:** `frontend/src/components/ConfigPanel.tsx` (Chapter-naming `TextInput` description, ~lines 189-191; `Code` already imported line 6)
- [ ] **Step 1:** replace the string description with a JSX fragment:
```tsx
              description={
                <>
                  Names each CBZ from a Jinja2 template. Example:{" "}
                  <Code>{"{{ series }} - {{ chapter }} - {{ title }}"}</Code>. Variables: series,
                  manga, chapter, chapter_number, title, volume, lang, author, date.
                </>
              }
```
- [ ] **Step 2: Verify** (typecheck — description accepts ReactNode; the `{{ }}` is a string child of `<Code>`) **+ Step 3: Commit** — `git commit -am "copy(config): worked example for chapter template"`

### Task H5: ConfigPanel — replace "Bumping this" + restart requirement

**Files:** `frontend/src/components/ConfigPanel.tsx` (Parallelism FormSection description, ~lines 239-243)
- [ ] **Step 1:** `description="Applied at startup. Bumping this speeds up CBZ packing inside one job but adds disk I/O."` → `description="Restart the service to apply a change here. A higher value packs more CBZs at once within a single job — faster, but with heavier disk I/O."`
- [ ] **Step 2: Verify + Step 3: Commit** — `git commit -am "copy(config): explicit restart requirement on parallelism"`

### Task H6: MaintenancePanel — rewrite "fan out"/"idempotent"

**Files:** `frontend/src/components/MaintenancePanel.tsx` (intro Text, ~lines 74-77)
- [ ] **Step 1:** → `One-off jobs that sweep the whole library: rename CBZs, refresh series metadata. Safe to run repeatedly (idempotent) — re-running won't double up or undo earlier runs.`
- [ ] **Step 2: Verify + Step 3: Commit** — `git commit -am "copy(maintenance): plain-language intro"`

### Task H7: MaintenancePanel — fix stale empty-state parenthetical

**Files:** `frontend/src/components/MaintenancePanel.tsx` (EmptyState body, ~lines 150-154)
- [ ] **Step 1:** `body="Scheduled background jobs (rename, regenerate, rebuild) and their results show up here."` → `body="Jobs you schedule above — and what they did — show up here."`
- [ ] **Step 2: Verify + Step 3: Commit** — `git commit -am "copy(maintenance): drop stale job-list parenthetical"`

### Task H8: RebuildLibraryCard — clarify the SERVICE is unavailable

**Files:** `frontend/src/components/RebuildLibraryCard.tsx` (description Text, ~lines 40-45)
- [ ] **Step 1:** replace the trailing `There's no undo. Plan to be offline for several hours.` with `There's no undo. Expect the library to be rebuilding — and downloads to stay incomplete — for several hours.`
- [ ] **Step 2: Verify + Step 3: Commit** — `git commit -am "copy(rebuild): clarify the service, not the user, is unavailable"`

---

# Phase 4 — Polish (Workstreams I, J, K)

## Workstream I — Narrow-row meta crowding (runs AFTER G)

### Task I1: RecentRow chapter chip wraps

**Files:** Modify `frontend/src/components/RecentRow.tsx`; update `frontend/src/components/RecentRow.test.tsx`

- [ ] **Step 1: Write the failing test** — add to the existing `describe("RecentRow chapter label")` block (assert the **post-G4** `chapters` string):

```tsx
  it("lets the chapter meta wrap (no inline white-space:nowrap) so it doesn't crowd the row", () => {
    renderWithProviders(
      <RecentRow
        item={makeJob({ chapters_total: 40, postprocess_chapters_packed: 12, chapters_failed: 3 })}
        selected={false}
        cancelling={false}
        inflight={false}
        isCancelPending={false}
        isRequeuePending={false}
        onSelect={noop}
        onCancel={noop}
        onRequeue={noop}
      />,
    );
    const meta = screen.getByText(/12\/40 chapters/);
    expect(meta.style.whiteSpace).toBe("");
  });
```

- [ ] **Step 2: Run — expect FAIL** (`whiteSpace` is `nowrap`).
- [ ] **Step 3: Implement** — `RecentRow.tsx` (lines 68-70): remove `style={{ whiteSpace: "nowrap" }}` from the chapter-count `<Text>` (keep `size`/`c`/`ff`). The wrap behaviour already exists via `.app-row-line { flex-wrap: wrap }` under the 480px container query.
- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green. Visual: ≤480px the chip wraps below the name.
- [ ] **Step 5: Commit** — `git commit -am "fix(recent-row): let chapter meta wrap on narrow rows"`

### Task I2: RunningJobsPanel mirrors the URL subtitle

**Files:** Modify `frontend/src/components/RunningJobsPanel.tsx`; update `frontend/src/components/RunningJobsPanel.test.tsx` (created in G3)

- [ ] **Step 1: Write the failing tests** — append a `describe` to `RunningJobsPanel.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Download } from "../api/types.gen";
import { renderWithProviders } from "../test/render";

vi.mock("../api/@tanstack/react-query.gen", () => ({
  listDownloadsOptions: () => ({ queryKey: ["downloads"], queryFn: async () => mockList }),
}));

let mockList: Download[] = [];

function makeRunning(overrides: Partial<Download>): Download {
  return {
    id: 1, url: "https://example/series-x", name: "Series X", extractor: "fake",
    status: "running", created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z",
    finished_at: null, exit_code: null, files_downloaded: 0, files_expected: null,
    chapters_total: 5, chapters_discovered: 5, chapters_failed: 0, error: null,
    postprocess_status: null, postprocess_chapters_packed: null, postprocess_error: null,
    output_dir: null, target_id: null, ...overrides,
  } as Download;
}

describe("RunningJobsPanel URL subtitle", () => {
  it("renders the URL as a subtitle when the series has a name", async () => {
    mockList = [makeRunning({ id: 7, name: "Series X", url: "https://example/series-x" })];
    const { RunningJobsPanel } = await import("./RunningJobsPanel");
    renderWithProviders(<RunningJobsPanel onSelect={() => {}} selectedId={null} />);
    expect(await screen.findByText("Series X")).toBeInTheDocument();
    expect(screen.getByText("https://example/series-x")).toBeInTheDocument();
  });

  it("omits the subtitle when there is no name (URL is already the heading)", async () => {
    mockList = [makeRunning({ id: 8, name: null, url: "https://example/no-name" })];
    const { RunningJobsPanel } = await import("./RunningJobsPanel");
    renderWithProviders(<RunningJobsPanel onSelect={() => {}} selectedId={null} />);
    expect(await screen.findAllByText("https://example/no-name")).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (no subtitle rendered).
- [ ] **Step 3: Implement** — `RunningJobsPanel.tsx`: after `const displayName = item.name ?? item.url;` add `const showUrlSubtitle = Boolean(item.name);`. Inside the row `<Stack gap={4}>`, immediately after the `app-row-line` `</div>`, insert (mirrors RecentRow):
```tsx
        {showUrlSubtitle && (
          <Text className="app-url app-row-url" title={item.url}>
            {item.url}
          </Text>
        )}
```
(The `app-url app-row-url` classes already participate in the 480px container wrap; no CSS change.)

- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green.
- [ ] **Step 5: Commit** — `git commit -am "feat(running-jobs): mirror URL subtitle for consistent density"`

## Workstream J — Maintenance result cell (expandable)

### Task J1: Add the co-located `MaintResultCell` component

**Files:** Modify `frontend/src/components/MaintenancePanel.tsx`

- [ ] **Step 1: Append `MaintResultCell` below `export function MaintenancePanel()`'s closing brace (after line 268).** Add `UnstyledButton` to the `@mantine/core` import (lines 1-14) and `IconChevronDown` to the `./Icons` import (line 28). `useState`, `Stack`, `Text` are already imported.

```tsx
function MaintResultCell({
  text,
  empty,
  jobId,
}: {
  text: string;
  empty: boolean;
  jobId: number;
}) {
  const [expanded, setExpanded] = useState(false);

  // No payload and no error: nothing to expand, just the placeholder.
  if (empty) {
    return (
      <Text size="xs" ff="monospace" c="dimmed">
        {text}
      </Text>
    );
  }

  return (
    <Stack gap={4} className="maint-result-wrap">
      {expanded ? (
        <Text
          size="xs"
          ff="monospace"
          c="dimmed"
          className="maint-result maint-result-full"
          data-testid={`maint-result-full-${jobId}`}
        >
          {text}
        </Text>
      ) : (
        <Text size="xs" ff="monospace" c="dimmed" className="maint-result">
          {text}
        </Text>
      )}
      <UnstyledButton
        className="maint-result-toggle"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
        aria-expanded={expanded}
        aria-label={
          expanded
            ? `Collapse result for maintenance job ${jobId}`
            : `Expand result for maintenance job ${jobId}`
        }
        data-expanded={expanded ? "true" : undefined}
      >
        <Text size="xs" c="dimmed" ff="monospace">
          {expanded ? "collapse" : "expand"}
        </Text>
        <IconChevronDown size={14} className="maint-result-toggle-chev" />
      </UnstyledButton>
    </Stack>
  );
}
```

- [ ] **Step 2: Verify** — `mise run typecheck` green (component compiles; not yet wired).
- [ ] **Step 3: Commit** — `git commit -am "feat(maintenance): add MaintResultCell expand/collapse component"`

### Task J2: Wire the result cell + test expand/collapse

**Files:** Modify `frontend/src/components/MaintenancePanel.tsx`; update `frontend/src/components/MaintenancePanel.test.tsx`

- [ ] **Step 1: Write the failing test** — add to `MaintenancePanel.test.tsx` (uses `fireEvent`):

```tsx
  it("keeps the result payload collapsed by default and expands it inline on tap", async () => {
    const nextId = { value: 2 };
    const jobs: Job[] = [
      {
        id: 1, kind: "rename_chapters", status: "completed",
        created_at: "2025-01-01T00:00:00", started_at: "2025-01-01T00:00:01",
        finished_at: "2025-01-01T00:00:02", result: { renamed: 7 }, error: null,
      },
    ];
    const progress: Record<number, { status: string; total: number; done: number; lines: string[] }> = {
      1: { status: "completed", total: 7, done: 7, lines: ["done"] },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    const toggle = await screen.findByRole("button", { name: /expand result for maintenance job 1/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(/\{"renamed":7\}/)).toBeInTheDocument();
    expect(screen.queryByTestId("maint-result-full-1")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /collapse result for maintenance job 1/i })).toBeInTheDocument();
    expect(screen.getByTestId("maint-result-full-1")).toHaveTextContent('{"renamed":7}');

    fireEvent.click(screen.getByRole("button", { name: /collapse result for maintenance job 1/i }));
    expect(screen.getByRole("button", { name: /expand result for maintenance job 1/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("maint-result-full-1")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run — expect FAIL** (no toggle button).
- [ ] **Step 3: Implement** — replace the result `<Table.Td>` (lines 214-218) with:
```tsx
                        <Table.Td>
                          <MaintResultCell
                            text={job.result ? JSON.stringify(job.result) : (job.error ?? "—")}
                            empty={!job.result && !job.error}
                            jobId={job.id}
                          />
                        </Table.Td>
```
(The `<Table.Tr>` row onClick selects the job — the toggle's `e.stopPropagation()` already prevents hijacking selection.)

- [ ] **Step 4: Run — expect PASS.** Lint/typecheck green.
- [ ] **Step 5: Commit** — `git commit -am "feat(maintenance): expandable result cell"`

### Task J3: `.maint-result-full` / `.maint-result-toggle` CSS

**Files:** Modify `frontend/src/styles/global.css` (after the `.maint-result {}` block, before the `@media (--bp-maint)` block ~line 859)

- [ ] **Step 1: Insert:**
```css

/* Expanded result: drop the line clamp so the full payload reads inline,
   collapsed by default via the tap-to-expand toggle below. */
.maint-result-full {
  -webkit-line-clamp: unset;
  line-clamp: unset;
  display: block;
  overflow: visible;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Inline expand/collapse affordance for the result cell. Mirrors the
   .maint-log-toggle look (chevron + mono label) but is visible on every
   viewport, since wide JSON is clipped on desktop too. */
.maint-result-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  align-self: flex-start;
  padding: 2px 6px;
  border-radius: var(--mantine-radius-sm);
  border: 1px solid var(--app-border-subtle);
}
.maint-result-toggle:hover {
  background: var(--app-surface-muted);
}
.maint-result-toggle-chev {
  transition: transform 120ms ease;
}
.maint-result-toggle[data-expanded="true"] .maint-result-toggle-chev {
  transform: rotate(180deg);
}
```
- [ ] **Step 2: Verify** — maintenance table, desktop + ≤640px, both schemes: collapsed shows clamped lines + `expand ⌄` chip; tap expands inline + rotates chevron; tap again collapses; toggle does not select the row. Lint green.
- [ ] **Step 3: Commit** — `git commit -am "style(maintenance): expandable result cell affordance"`

## Workstream K — Off-system one-offs + viewport-aware Jobs

### Task K1: UpdateLxcCard grape Badge → `.pill` (info)

**Files:** Modify `frontend/src/components/UpdateLxcCard.tsx` (UpdateAvailabilityBanner, ~lines 260-264)

- [ ] **Step 1: Edit** — replace:
```tsx
              <Badge color="grape" variant="light" size="sm">
                preview · {check.tracked_ref}
              </Badge>
```
with:
```tsx
              <Pill tone="info" noDot>
                preview · {check.tracked_ref}
              </Pill>
```
Add `import { Pill } from "./Pill";` and remove `Badge` from the `@mantine/core` import (only usage in the file).

- [ ] **Step 2: Verify** — `mise run lint` + `mise run typecheck` green (no unused `Badge`); `preview · <ref>` renders as `.pill[data-tone="info"]`, both schemes. `MaintenancePanel.test.tsx` preview-ref banner case still passes.
- [ ] **Step 3: Commit** — `git commit -am "style(update-lxc): preview marker uses five-tone pill"`

### Task K2: MaintenancePanel ✕ ActionIcon → `.icon-btn` (relies on B1 for 44px)

**Files:** Modify `frontend/src/components/MaintenancePanel.tsx` (Actions Table.Td, ~lines 219-238)

- [ ] **Step 1: Edit** — replace the cancel `<ActionIcon>…✕…</ActionIcon>` with:
```tsx
                              <button
                                type="button"
                                className="icon-btn"
                                data-tone="danger"
                                aria-label={`Cancel maintenance job ${job.id}`}
                                disabled={
                                  cancel.isPending && cancel.variables?.path?.job_id === job.id
                                }
                                onClick={(e) => {
                                  e.stopPropagation();
                                  cancel.mutate({ path: { job_id: job.id } });
                                }}
                              >
                                <IconX size={16} />
                              </button>
```
Add `IconX` to the `./Icons` import (line 28); remove `ActionIcon` from `@mantine/core` if now unused (grep first). **No `data-size`** — B1's `.maint-jobs-table .icon-btn` rule promotes it to 44px at phone width.

- [ ] **Step 2: Verify** — `mise run lint` + `mise run typecheck` green; cancel renders as `.icon-btn[data-tone="danger"]` (matches ActiveJobCard), danger-tinted hover; 44px at ≤540px. `MaintenancePanel.test.tsx` green (`aria-label` preserved; in-flight maps to `disabled`).
- [ ] **Step 3: Commit** — `git commit -am "style(maintenance): cancel uses icon-btn utility"`

### Task K3: JobStepper — hide the whole Stepper track on phones (keep caption)

**Files:** Modify `frontend/src/components/JobStepper.tsx`, `frontend/src/styles/global.css`

- [ ] **Step 1: Wrap the Stepper in a track div (JobStepper.tsx ~lines 20-35)** — wrap the `<Stepper>…</Stepper>` in `<Box className="active-job-stepper-track"> … </Box>` (the `.active-job-step-caption` `<Text>` stays a sibling, outside the track).
- [ ] **Step 2: Replace the phone label-hiding rules in `global.css`** — inside the `@media (--bp-phone)` active-job block (~lines 1212-1216), replace the `.active-job-stepper .mantine-Stepper-stepLabel, …-stepDescription, …-stepBody { display: none; }` rule (and the orphaned `.mantine-Stepper-separator` rule) with:
```css
  .active-job-stepper-track {
    display: none;
  }
```
(Leave the `.active-job-step-caption` default `display: none` / phone `display: block` untouched.)

- [ ] **Step 3: Verify** — ≤540px: the bare six-icon row is gone, only the `Step N of 6 — <Name>` caption remains; desktop: full Stepper, caption hidden. Lint/typecheck green. Both schemes.
- [ ] **Step 4: Commit** — `git commit -am "fix(job-stepper): drop decorative icon row on phones"`

### Task K4: JobsTabBody viewport-aware (never two-column on phones)

**Files:** Modify `frontend/src/App.tsx`; Create `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests** (`App.test.tsx`)

```tsx
import { describe, expect, it, vi } from "vitest";
import { JobsTabBody } from "./App";
import { jsonResponse, mockFetch } from "./test/mocks";
import { renderWithProviders } from "./test/render";

const useMediaQueryMock = vi.fn();
vi.mock("@mantine/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mantine/hooks")>();
  return { ...actual, useMediaQuery: (...args: unknown[]) => useMediaQueryMock(...args) };
});

describe("JobsTabBody viewport-aware grid", () => {
  function arrange() {
    mockFetch(async () => jsonResponse([]));
  }

  it("renders the two-column .jobs-grid when wide and a job is selected", () => {
    useMediaQueryMock.mockReturnValue(true);
    arrange();
    const { container } = renderWithProviders(
      <JobsTabBody selectedId={7} onSelect={() => {}} hasAnyActive />,
    );
    expect(container.querySelector(".jobs-grid")).not.toBeNull();
  });

  it("never enters .jobs-grid on a narrow viewport even with a selection", () => {
    useMediaQueryMock.mockReturnValue(false);
    arrange();
    const { container } = renderWithProviders(
      <JobsTabBody selectedId={7} onSelect={() => {}} hasAnyActive />,
    );
    expect(container.querySelector(".jobs-grid")).toBeNull();
    expect(useMediaQueryMock).toHaveBeenCalledWith(expect.stringContaining("min-width"), true);
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (`JobsTabBody` not exported / not viewport-aware).
- [ ] **Step 3: Implement** — in `App.tsx`: add `useMantineTheme` to the `@mantine/core` import (line 1) and `import { useMediaQuery } from "@mantine/hooks";`. **Export** `JobsTabBody` and make it viewport-aware (lines 177-207):

```tsx
export function JobsTabBody({
  selectedId,
  onSelect,
  hasAnyActive,
}: {
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  hasAnyActive: boolean;
}) {
  const theme = useMantineTheme();
  // The two-column .jobs-grid only collapses to one column at --bp-split (880px)
  // via CSS; below it the ActiveJobCard still mounts inside the grid wrapper and
  // fights the single column. Gate grid *entry* on viewport too so a selection
  // never forces the grid on a narrow screen. `true` initial value keeps the
  // desktop layout on first paint (matches the >=880px common case).
  const wide = useMediaQuery(`(min-width: ${theme.breakpoints.split})`, true);
  const hasSelection = selectedId !== null;
  if (!hasSelection || !wide) {
    return (
      <Stack gap="lg">
        <RunningJobsPanel onSelect={onSelect} selectedId={selectedId} />
        <RecentList
          onSelect={onSelect}
          selectedId={selectedId}
          hideEmpty={!hasSelection && !hasAnyActive}
        />
        {hasSelection ? (
          <ActiveJobCard jobId={selectedId} onClose={() => onSelect(null)} />
        ) : null}
      </Stack>
    );
  }
  return (
    <div className="jobs-grid">
      <Stack gap="md">
        <RunningJobsPanel onSelect={onSelect} selectedId={selectedId} />
        <RecentList onSelect={onSelect} selectedId={selectedId} />
      </Stack>
      <ActiveJobCard jobId={selectedId} onClose={() => onSelect(null)} />
    </div>
  );
}
```
(Uses `theme.breakpoints.split` from A2 — 880px. The stacked branch appends `ActiveJobCard` so the close affordance survives on phones; `hideEmpty` now keeps the recent list visible when a job is selected.)

- [ ] **Step 4: Run — expect PASS.** `mise run test:frontend` + `mise run typecheck` + `mise run lint` green. Manual: <880px a selected job stacks instead of splitting.
- [ ] **Step 5: Commit** — `git commit -am "feat(jobs): viewport-aware layout — never two-column on phones"`

---

# Final verification

- [ ] **Run the full gate:** `mise run check` (lint + typecheck + test) → all green.
- [ ] **Manual responsive pass:** load the app, exercise every tab at **430px and desktop in BOTH colour schemes** — confirm touch targets are 44px on phone, forms/toolbars reflow one-per-row, no horizontal scroll, the Jobs view stacks on phones, the maintenance result cell expands, copy reads on-voice, and reduced-motion is respected (DevTools emulation).
- [ ] **Finish the branch** via superpowers:finishing-a-development-branch (PR to `main`).

# Self-review notes (resolved)

- **Spec coverage:** every workstream A–K and every spec workstream maps to tasks above (A1–A2, B1–B5, C1–C8, D1–D3, E1–E3, F1, G1–G12, H1–H8, I1–I2, J1–J3, K1–K4).
- **Type consistency:** K4 reads `theme.breakpoints.split` (defined in A2), not the draft's nonexistent `.lg`. A2 keeps Mantine default keys so `<Container size="lg">` is unaffected. B1's `.maint-jobs-table .icon-btn` rule and K2's converted button are the same selector/element (44px once, not twice). G4 renames the unit and I1 asserts the post-rename `chapters` string.
- **No placeholders:** every code step shows the exact current→new content; every logic task has real test code + a failing-first run.
