import { Tabs } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { listDownloadsOptions } from "./api/@tanstack/react-query.gen";
import { ConfigPanel } from "./components/ConfigPanel";
import { CountBadge } from "./components/CountBadge";
import { HealthBadge } from "./components/HealthBadge";
import { JobsView } from "./components/JobsView";
import { LibraryView } from "./components/LibraryView";
import { LogsPanel } from "./components/LogsPanel";
import { MaintenancePanel } from "./components/MaintenancePanel";
import { MobileMenuButton } from "./components/MobileMenuButton";
import { MobileNavDrawer } from "./components/MobileNavDrawer";
import { ThemeToggle } from "./components/ThemeToggle";
import { useAutoSelectJob } from "./hooks/useAutoSelectJob";
import { initialJobIdFromUrl, useSyncJobParam } from "./hooks/useRouteJob";
import { useRouteTab } from "./hooks/useRouteTab";
import { useEventStream } from "./lib/eventStream";
import { REFETCH_LIST_MS } from "./lib/polling";
import { isRunning, isScheduled } from "./lib/status";

export default function App() {
  // Open one websocket for the app lifetime — push events into the cache so
  // lists refresh immediately on server-side state changes.
  useEventStream();
  const [tab, setTab] = useRouteTab();
  const [navOpen, setNavOpen] = useState(false);

  const { data: downloads } = useQuery({
    ...listDownloadsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });
  const { running, scheduled } = useMemo(() => {
    const list = downloads ?? [];
    return {
      running: list.reduce((n, d) => n + (isRunning(d.status) ? 1 : 0), 0),
      scheduled: list.reduce((n, d) => n + (isScheduled(d.status) ? 1 : 0), 0),
    };
  }, [downloads]);

  // `?job=` deep link: read once on load (a manual pick from the URL), then
  // mirror manual selections back into the URL so reload/share keeps them.
  const [initialJobId] = useState(initialJobIdFromUrl);
  const { selectedId, isManualSelection, selectJob } = useAutoSelectJob(downloads, initialJobId);
  useSyncJobParam(tab, isManualSelection ? selectedId : null);

  const openJob = (id: number) => {
    selectJob(id);
    setTab("jobs");
  };

  // Clicking the brand returns to the library (the app's "home"). We keep the
  // element as a real <a href="/library"> so middle-click / cmd-click open in
  // a new tab, then intercept the plain click to route via setTab() — the SPA
  // owns navigation and a full reload would be wasteful.
  const handleBrandClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (e.defaultPrevented) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    setTab("library");
  };

  // One Tabs root spans the header (where the tab list lives) and the body
  // (the panels). Every tab is one screen sized to the viewport below the
  // header, with panes that scroll on their own (see Screen).
  return (
    <Tabs value={tab} onChange={setTab} keepMounted variant="default" className="app-tabs">
      <a href="#main" className="app-skip-link">
        Skip to main content
      </a>
      <header className="app-shell-header">
        <div className="app-shell-header-inner">
          <a
            href="/library"
            className="app-brand"
            aria-label="gallery-dl-webui — go to library"
            aria-current={tab === "library" ? "page" : undefined}
            onClick={handleBrandClick}
          >
            <span className="app-brand-mark" aria-hidden="true">
              g
            </span>
            <h1 className="app-brand-word">gallery-dl-webui</h1>
            <span className="app-brand-tag" aria-hidden="true">
              archive
            </span>
          </a>
          <Tabs.List className="app-nav">
            <Tabs.Tab value="library">Library</Tabs.Tab>
            <Tabs.Tab
              value="jobs"
              rightSection={<CountBadge running={running} queued={scheduled} />}
            >
              Jobs
            </Tabs.Tab>
            <Tabs.Tab value="config">Config</Tabs.Tab>
            <Tabs.Tab value="maintenance">Maintenance</Tabs.Tab>
            <Tabs.Tab value="logs">Logs</Tabs.Tab>
          </Tabs.List>
          <div className="app-shell-header-meta">
            <HealthBadge />
            <ThemeToggle />
            <MobileMenuButton open={navOpen} onClick={() => setNavOpen((o) => !o)} />
          </div>
        </div>
      </header>
      <main id="main" className="app-shell-main" data-tab={tab}>
        <Tabs.Panel value="library">
          <LibraryView tab={tab} onOpenJob={openJob} />
        </Tabs.Panel>
        <Tabs.Panel value="jobs">
          <JobsView
            selectedId={selectedId}
            isManualSelection={isManualSelection}
            onSelect={selectJob}
          />
        </Tabs.Panel>
        <Tabs.Panel value="config">
          <ConfigPanel />
        </Tabs.Panel>
        <Tabs.Panel value="maintenance">
          <MaintenancePanel />
        </Tabs.Panel>
        <Tabs.Panel value="logs">
          {/* Only mount when active so the SSE stream is opened on demand
              and torn down when the user navigates away. */}
          {tab === "logs" ? <LogsPanel /> : null}
        </Tabs.Panel>
      </main>
      <MobileNavDrawer
        active={tab}
        open={navOpen}
        jobsBadge={running}
        onChange={(k) => setTab(k)}
        onClose={() => setNavOpen(false)}
      />
    </Tabs>
  );
}
