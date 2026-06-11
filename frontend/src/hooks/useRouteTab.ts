import { useCallback, useEffect, useState } from "react";

export const TABS = ["library", "jobs", "config", "maintenance", "logs"] as const;
export type Tab = (typeof TABS)[number];
const DEFAULT_TAB: Tab = "library";

function isTab(v: unknown): v is Tab {
  return typeof v === "string" && (TABS as readonly string[]).includes(v);
}

export function pathnameToTab(pathname: string): Tab {
  const seg = pathname.replace(/^\/+/, "").split("/")[0] ?? "";
  return isTab(seg) ? seg : DEFAULT_TAB;
}

/**
 * Sync the active tab with the URL so a reload preserves the user's place
 * and the browser back/forward buttons move between tabs. The backend's SPA
 * fallback ({@link ../../../backend/src/backend/main.py}) returns `index.html`
 * for any non-`/api` path, which is what makes a hard load on `/jobs` work.
 */
export function useRouteTab(): readonly [Tab, (next: Tab | string | null) => void] {
  const [tab, setTabState] = useState<Tab>(() => pathnameToTab(window.location.pathname));

  useEffect(() => {
    const onPop = () => setTabState(pathnameToTab(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const setTab = useCallback((next: Tab | string | null) => {
    if (!isTab(next)) return;
    const path = `/${next}`;
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setTabState(next);
  }, []);

  return [tab, setTab] as const;
}
