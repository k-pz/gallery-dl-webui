import { type ScreenLayout, useScreenLayout, useScreenRail } from "./useScreenLayout";

/**
 * Library layout: the shared screen tiers (see useScreenLayout), where
 *
 *   ultra  list · details · EPUB packer side by side (+ activity column
 *          from 2900px)
 *   split  list + one detail pane with tabs
 *   stack  list, then a full-screen series view
 */
export type LibraryLayout = ScreenLayout;

export function useLibraryLayout(): { layout: LibraryLayout; showRail: boolean } {
  return { layout: useScreenLayout(), showRail: useScreenRail() };
}
