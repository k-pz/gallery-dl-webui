/**
 * Deep-linking for the library's selected series: `/library?series=12`.
 *
 * Like `?job=` on the Jobs tab, only a series the user picked is mirrored
 * into the URL; the one auto-selected on wide screens is not, so a reload
 * keeps following the list instead of pinning that series.
 */

import { useEffect } from "react";
import { pathnameToTab, type Tab } from "./useRouteTab";

const PARAM = "series";

/** Parse `?series=` from the current URL when the page loads on the Library tab. */
export function initialSeriesIdFromUrl(): number | null {
  if (pathnameToTab(window.location.pathname) !== "library") return null;
  const raw = new URLSearchParams(window.location.search).get(PARAM);
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return id > 0 ? id : null;
}

/**
 * Mirror the picked series into `?series=` while on the Library tab, and
 * drop the param elsewhere. replaceState keeps selections out of history so
 * back/forward still moves between tabs.
 */
export function useSyncSeriesParam(tab: Tab, seriesId: number | null) {
  useEffect(() => {
    const url = new URL(window.location.href);
    const desired = tab === "library" && seriesId !== null ? String(seriesId) : null;
    if (url.searchParams.get(PARAM) === desired) return;
    if (desired === null) url.searchParams.delete(PARAM);
    else url.searchParams.set(PARAM, desired);
    window.history.replaceState(window.history.state, "", url);
  }, [tab, seriesId]);
}
