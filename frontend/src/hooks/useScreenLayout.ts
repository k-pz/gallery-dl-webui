import { useMediaQuery } from "@mantine/hooks";

/**
 * Screen layout tiers shared by every tab. These mirror the `--bp-lib-*`
 * custom media in styles/global.css (keep in sync; both are device px):
 *
 *   ultra  ≥ 2400  every pane side by side (the default on ultra-wide)
 *   split  900–2399  a list pane beside one detail pane (touch screens get
 *                    larger targets from CSS)
 *   stack  < 900   phones and portrait tablets: panes flow with the page;
 *                  a picked item opens full screen with a back button
 *
 * Only the structural choices (which panes exist) are made in JS; sizing
 * stays in CSS.
 */
export const SCREEN_ULTRA_QUERY = "(min-width: 2400px)";
export const SCREEN_RAIL_QUERY = "(min-width: 2900px)";
export const SCREEN_STACK_QUERY = "(max-width: 899px)";

export type ScreenLayout = "ultra" | "split" | "stack";

const opts = { getInitialValueInEffect: false } as const;

export function useScreenLayout(): ScreenLayout {
  const ultra = useMediaQuery(SCREEN_ULTRA_QUERY, false, opts) ?? false;
  const stack = useMediaQuery(SCREEN_STACK_QUERY, false, opts) ?? false;
  return ultra ? "ultra" : stack ? "stack" : "split";
}

/** True from 2900px, where an extra activity column fits. */
export function useScreenRail(): boolean {
  return useMediaQuery(SCREEN_RAIL_QUERY, false, opts) ?? false;
}
