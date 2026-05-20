# Interactions

How the UI behaves beyond the static layouts. The implementation lives in
`frontend/src/lib/eventStream.ts`, `lib/optimisticCancel.ts`,
`lib/invalidate.ts`, plus per-component mutation callbacks.

## Realtime updates

The app opens one websocket to `/api/ws` at mount and keeps it open for the
session. Server-side events get pushed into the TanStack Query cache —
every list or single-entity view re-renders within ~milliseconds of the
backend transitioning state.

**What the user feels:**
- A submitted URL appears in the Library list and Jobs list essentially
  instantly.
- The active job's stepper advances stage-by-stage as the worker progresses.
- Chapter badges in the progress card flip from `DOWNLOADING` → `DOWNLOADED`
  → `PROCESSING` → `COMPLETED` without the user doing anything.
- The Jobs tab badge count (`1/0` etc.) ticks in lockstep.

**Fallback polling:**
Lists also set `refetchInterval: 10_000` and the active job sets `5_000`.
These only matter when the websocket has been disconnected (suspended
laptop, proxy timeout). On reconnect the event stream re-syncs every cached
list — there's no missed-update window the user can see.

There's no spinner spam during background refetches. `<ListHeader>` shows a
small `<Loader size="xs">` next to the count while `isLoading` is true on
the very first fetch only; subsequent refetches are silent.

## Optimistic cancel

Clicking Cancel on a job (in the active card or in a list row) flips an
*optimistic* "Cancelling…" state immediately — the badge swaps to orange
"Cancelling…" and the cancel button itself spins. The actual server-side
status transition (pending/running → cancelled) arrives a moment later via
the websocket and the optimistic flag clears.

This avoids the "did my click work?" feeling: there's never a moment
between user click and visible feedback.

Lives in `lib/optimisticCancel.ts`.

## Notifications

Mantine `Notifications` at `position="top-right"`. Toasts fire from
mutation callbacks (`onSuccess` / `onError`) and never from background
refetches.

| Action               | Title              | Color    |
|----------------------|--------------------|----------|
| Submit gallery       | "Job queued"       | green    |
| Submit fails         | "Submission failed"| red      |
| Cancel               | "Cancel requested" | orange   |
| Cancel fails         | "Cancel failed"    | red      |
| Requeue              | "Requeued"         | blue     |
| Requeue fails        | "Requeue failed"   | red      |
| Target poll          | "Poll queued"      | blue     |
| Target poll fails    | "Poll failed"      | red      |
| Target delete        | "Target removed"   | gray     |
| Target delete fails  | "Delete failed"    | red      |

Patterns:
- Title is short (1–3 words).
- Message is one sentence ending in a period — generally `"Job #N {verb}."`.
- Failure colors are always red. Success uses green for *new* outcomes,
  blue for re-runs/info, gray for deletions.

There are **no toasts for routine background events** (a job completing,
the websocket reconnecting, etc.). The user sees those via the UI
re-rendering, not via a notification.

## Modals + confirms

Two patterns today:

1. **Native `window.confirm()`** — used for destructive operations:
   - Removing a target from the library (`TargetsList.tsx`).
   - Rebuilding the library (`MaintenancePanel.tsx`).

   This is a deliberate choice (small surface area, no design needed) but
   it reads poorly on macOS where the dialog is non-themed. See
   [open-questions.md](open-questions.md).

2. **Inline expand** — preferred. The DirectoryPicker's "Create folder"
   form expands a `<Paper>` block inline within the picker rather than
   opening a modal. Inputs land focused, Enter submits, Escape… closes
   (well, the Cancel button does — there's no Escape handler).

There are no Mantine `<Modal>` instances anywhere.

## Theme switching

The Config tab has an Auto / Light / Dark `<SegmentedControl>`. Selecting
one writes to `localStorage` (`mantine-color-scheme-value`) and Mantine
immediately re-renders the tree with the new scheme — no reload.

To avoid the FOUC flash on cold load, an inline `<script>` in
`index.html` reads the persisted value and sets `data-mantine-color-scheme`
on `<html>` before React mounts.

## Filtering + sorting

Filters live in component-local `useState`, not in the URL. That means
filter state is lost on a hard reload — by design, since there's no
deep-linking story (single-user, single-page).

The Jobs list defaults to status filter "Active" and sort "Queue order
↑" — the user lands on the "what should I worry about right now" view.

The kicker on the Jobs list mirrors the filter:
- `queue` when filter = Active (the default).
- `history` when filter is one of Completed/Failed/Cancelled.
- `all jobs` when filter = Any.

This is a tiny but deliberate copy detail — the same card communicates
*what slice of the dataset is being shown* through its label, not its
content.

## Keyboard

Best-effort, not exhaustive.

- **Enter** in the Submit form's URL input → submits.
- **Enter** in the DirectoryPicker's "New folder name" input → creates.
- **Enter** in a Library row's "Poll every" input → saves.
- **Enter / Space** on a list row (`.app-row`) → selects it.
- **Tab** flows through the major controls in source order.

No global shortcuts (`?`, `/`, `g j` for jump-to-jobs, etc). All
keyboard navigation is single-step.

## Accessibility notes

What's been done:
- Every ActionIcon has an `aria-label` (often parametrised — `Cancel #N`).
- The header `HealthBadge` uses `aria-live="polite"`.
- Pagination has `aria-label` describing the list it paginates.
- The dynamic-count badge on the Jobs tab has `aria-label="N running, M scheduled"`.
- The brand mark `g` and tag `ARCHIVE` are `aria-hidden="true"` so screen
  readers skip them and read the wordmark instead.
- Form inputs all have `label` + `description` (Mantine pairs them via
  `aria-describedby`).
- Color isn't the *only* status signal — badges always include text
  ("Downloading", "Completed", etc.).

What's missing / known gaps:
- The `.app-row` clickable rows pick up `role="button"` and keyboard
  activation but don't have explicit `aria-label`s. The visible content
  conveys the meaning.
- The native `window.confirm()` dialogs aren't keyboard-themeable.
- There's no skip-to-content link.
- Focus rings are Mantine defaults — not bespoke. Worth a pass.

## Responsiveness

The container caps at Mantine `size="lg"` (~1140px). Below that, everything
shrinks within the container. Below ~700px, the multi-column rows wrap
(`flex-wrap: wrap`) into stacks — every filter row, the Library row's
control strip, the active job's detail row.

The app **does not have a phone layout**. It's designed for desktop /
tablet width and assumes the user has at least ~720px of horizontal room.
The implementation is responsive in that it won't *break* on narrow
viewports, but rows don't reflow into a phone-friendly arrangement.

## Live progress detail

When the active job is running, the chapter list updates in place — each
chapter's stage badge transitions independently as files arrive. There's
no animation between badge states; the color just swaps. The progress
bar's value comes from `(non-downloading chapters) / (total chapters)` so
it ticks forward as chapters finish downloading and enter the
"downloaded" stage.

When the job completes, the bar fills, the stripes stop, and the chapter
list freezes with every row showing "Completed".
