import { useMediaQuery } from "@mantine/hooks";

/**
 * Library layout tiers. These mirror the `--bp-lib-*` custom media in
 * styles/global.css (keep in sync; both are device px):
 *
 *   ultra  ≥ 2400  list · details · EPUB packer side by side
 *   rail   ≥ 2900  ultra plus the activity column
 *   split  900–2399  list + one detail pane with tabs (tablets get touch
 *                    sizing from CSS below 1280)
 *   stack  < 900   phones and portrait tablets: list, then a full-screen
 *                  series view
 *
 * Only the structural choices (which panes exist) are made in JS; sizing
 * stays in CSS.
 */
export const LIB_ULTRA_QUERY = "(min-width: 2400px)";
export const LIB_RAIL_QUERY = "(min-width: 2900px)";
export const LIB_STACK_QUERY = "(max-width: 899px)";

export type LibraryLayout = "ultra" | "split" | "stack";

export function useLibraryLayout(): { layout: LibraryLayout; showRail: boolean } {
  const opts = { getInitialValueInEffect: false } as const;
  const ultra = useMediaQuery(LIB_ULTRA_QUERY, false, opts) ?? false;
  const rail = useMediaQuery(LIB_RAIL_QUERY, false, opts) ?? false;
  const stack = useMediaQuery(LIB_STACK_QUERY, false, opts) ?? false;
  const layout: LibraryLayout = ultra ? "ultra" : stack ? "stack" : "split";
  return { layout, showRail: rail };
}
