# Open questions

The actual brief. Where the current shipping design has rough edges, missing
patterns, or arbitrary choices that deserve a designer's pass.

Roughly ordered by impact — top items will shape the whole system, bottom
items are localised.

## 1. Is the "editorial" register the right one?

The whole visual language leans on:
- Serif headings (Fraunces).
- Warm off-white surface with a single amber accent.
- Hairline borders, near-no elevation.
- Mono for paths/numerics — reading slightly like a terminal.

This was a deliberate move *away* from the SaaS-admin look (filled buttons,
heavy shadows, color-coded everything). The question is whether the
register *carries* — does it still read like a tool, or has it drifted
into "blog post about manga"?

What to look at: the Library tab's `Series` row stack. It's the most
information-dense view and the place where the editorial choices have to
co-exist with controls, tags inputs, switches. Does it work?

If the answer is "register's right, sharpen it" — great. If "register's
wrong, here's a different lane" — equally welcome.

## 2. Status badge system

Two parallel systems exist right now:
- `<Badge variant="light" size="sm">` (Mantine) — used in nearly all
  visible rows.
- `.app-status-pill[data-tone="…"]` (bespoke CSS class) — defined in
  `global.css`, currently *not used* anywhere visible.

The bespoke pill was designed with:
- mono casing,
- a leading dot,
- subtler tone backgrounds (12–14% mix of tone + surface-muted).

The Mantine badge is sans, no dot, slightly higher chroma. The bespoke
pill is closer to what the rest of the UI looks like.

**Pick one**, then propagate. Either:
- Adopt the bespoke pill as the canonical status indicator everywhere.
- Decide it's overkill, delete it, lean fully into the Mantine badge.

While you're there, the chapter-stage badges in the progress card are
yet a third treatment (Mantine `light` with a different tone per stage —
blue, cyan, yellow, green). They should converge with whatever you pick.

## 3. The chapter list visual

The progress card's chapter list (the scrollable mono list inside an
`.app-surface-muted` box) is the most "data-heavy" piece in the UI. It
currently shows:
- chapter name in mono on the left,
- stage badge on the right,
- one row per chapter.

What it lacks:
- A clearer sense of *order* (the list is in extractor order, which the
  user has no mental model for).
- Per-chapter file counts (we have them in the backend; we don't show
  them).
- Differentiation between "queued chapter" and "completed chapter" —
  currently a Completed badge vs a Downloading badge, but the row itself
  doesn't change weight.

A pass here would benefit from thinking about it as a *sub-list-within-a-
list* — the active job is one row, the chapters are nested under it.

## 4. The "active job" hero card

The active job currently sits as its own card between the Running panel
and the Recent list. That makes it a *modal-like* hero when one job is
selected, then disappears when none is.

Open question: is that the right composition? Alternatives:
- Inline expand — clicking a row in the Recent list expands it in place
  rather than rendering a separate hero card above.
- Side panel — split the Jobs tab into list (left) + detail (right) at
  desktop widths.
- Modal — open the active job in an overlay.

Each has tradeoffs (real estate, scroll position, focus). The current
"hero card above the list" is the cheapest to implement; not necessarily
the most legible.

## 5. Destructive confirms

Two destructive actions use **`window.confirm()`** (native browser dialog):
- Removing a target from the library.
- Rebuilding the library (the biggest destructive op — wipes downloads
  AND postprocess output dirs).

These read poorly on macOS (un-themed, non-keyboard-friendly) and don't
provide a great place to explain the consequences. The rebuild-library
confirm is currently a 3-line text block crammed into a `confirm()` body.

A small `<Modal>` system with consistent layout (title, body, primary
destructive button, secondary cancel) is probably the right call. Open
question: design it.

## 6. Maintenance "Schedule" buttons

The three buttons in the Maintenance tab's first card are visually
inconsistent on purpose:
- Schedule chapter rename → filled primary (amber).
- Regenerate series metadata → light variant.
- Rebuild library → outline red.

The hierarchy reads as "primary / secondary / destructive" but the
visual gap between primary and secondary is large, and between secondary
and destructive is small. Does this match the actual destructiveness?
The "rebuild library" button is the only one that *cannot* be undone —
it deserves more visual weight, not less.

## 7. Iconography

Currently zero icons. Trailing actions on rows are Unicode glyphs
(`✕ ↻ ▶ +`). The brand mark is the letter `g`. There's no icon for "open
in new tab", "settings", "help", etc.

A modest icon set — say, 6–10 line icons in a single weight, tuned to sit
next to the body text — would fix a few rough spots:
- The ✕/↻/▶/+ glyphs render inconsistently across system fonts.
- "Open job #N →" uses a literal arrow; an icon component would let it
  inherit color/alignment properly.
- "Watch" toggles use a generic Switch; a watch/eye affordance would
  reinforce the metaphor.

Open question: is now the right time to pull in a set (Tabler / Lucide /
Phosphor — Mantine bundles Tabler), or stay with the Unicode-glyph
approach?

## 8. Empty states

Three different empty-state treatments exist:
- **Library empty** — dashed-border `--app-surface-muted` box with a
  multi-sentence hint ("Your library is empty. Submit a gallery URL
  above to start tracking a series.").
- **Jobs empty** — same box, shorter copy ("No jobs yet.").
- **Maintenance empty** — same box, copy ("No maintenance jobs yet.").
- **Filtered-to-empty** — bare `<Text size="sm" c="dimmed">` line, no
  box.

The dashed-border box treatment is fine but doesn't pull weight — it's
half an empty state. A real empty state might include:
- A directional cue ("Submit a gallery URL above") that visually points
  to the submit form.
- An illustration / wordmark variant.
- A "load library YAML" link as a side door.

## 9. Loading states

Every list shows a small `<Loader size="xs">` next to its count *only on
the very first fetch*. Subsequent refetches are silent.

The active job and config cards collapse to a centered "Loading job…" /
"Loading config…" spinner when they don't have data yet. This is jarring
— the card height changes between loading and loaded.

Better: skeleton states that match the layout. Mantine has `<Skeleton>`
but we don't use it anywhere. Open question: is the cost (more code) worth
the layout stability win?

## 10. Tags

Targets and downloads both support tags. They're rendered as Mantine's
`<TagsInput>` (the default chip-with-x pattern). It's functional but
visually loud — chips sit at the bottom of every Library row and clutter
the dense rows.

Open: should tags get their own treatment? Inline pills with no input,
expanding only on click? Or are they fine as-is?

## 11. The Jobs-tab badge count

The tab badge reads `1/0` (running/scheduled) when there's work. It's
the only place in the UI where a colon-separated tuple is shown — and
it's not obvious what the two numbers mean without context.

Alternatives:
- A single badge showing the total in-flight count.
- Two side-by-side badges with implicit color (blue = running, gray =
  scheduled).
- A textual badge: "1 running".

The current `1/0` reads like a chapter counter ("4 of 5"). Could be a
nicer affordance.

## 12. Sticky header on tall pages

The sticky header uses `backdrop-filter: blur(10px)` over a `88% bg` background.
On longer pages (especially Config), the blur reveals form content beneath
in a way that's *aesthetic* but reduces legibility. On screenshots, the
sticky behavior was disabled for capture — see
`frontend/designshots/capture.spec.ts`.

Two options:
- Drop the blur, keep the sticky.
- Drop the sticky, keep the calm aesthetic.

Either's defensible.

## 13. Color in dark mode

Dark mode uses `amber[4]` as accent (vs `amber[6]` in light) — a brighter,
more luminous gold. It works on the brand mark, but on the progress bar
it can read as orange-yellow against the deep ink background. Worth
sanity-checking against a real "active job" view.

## 14. Phone layout

There isn't one. The container caps at lg and below ~700px rows wrap into
stacks rather than reflow into a phone-friendly view. The app is desktop /
tablet only — not a stated goal to fix, but worth flagging.

---

If you'd like to scope a first pass: items 1, 2, 5, and 8 are the cluster
that would *most* change how the app reads. Items 3, 4, 6 are the next
layer down. Everything else is polish.
