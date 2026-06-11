/**
 * Deep-linking for the job detail pane: `/jobs?job=123`.
 *
 * Only user-made selections are reflected in the URL. Auto-opened jobs stay
 * out of it on purpose — they reproduce themselves on load anyway, and
 * persisting one would turn it into a "manual" pick after a reload, freezing
 * the auto-advance behaviour the user never opted out of.
 */

import { useEffect } from "react";
import { pathnameToTab, type Tab } from "./useRouteTab";

const PARAM = "job";

/**
 * Parse `?job=` from the current URL. Honoured only when the page loads on
 * the Jobs tab — that's where the detail pane lives.
 */
export function initialJobIdFromUrl(): number | null {
  if (pathnameToTab(window.location.pathname) !== "jobs") return null;
  const raw = new URLSearchParams(window.location.search).get(PARAM);
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return id > 0 ? id : null;
}

/**
 * Mirror the given job id into `?job=` while on the Jobs tab, and drop the
 * param otherwise. Pass null to keep the URL clean (no selection, or an
 * auto-opened one). Uses replaceState so selections don't pile up as
 * history entries — back/forward keeps moving between tabs.
 */
export function useSyncJobParam(tab: Tab, jobId: number | null) {
  useEffect(() => {
    const url = new URL(window.location.href);
    const desired = tab === "jobs" && jobId !== null ? String(jobId) : null;
    if (url.searchParams.get(PARAM) === desired) return;
    if (desired === null) {
      url.searchParams.delete(PARAM);
    } else {
      url.searchParams.set(PARAM, desired);
    }
    window.history.replaceState(window.history.state, "", url);
  }, [tab, jobId]);
}
