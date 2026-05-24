import { Box, Container, Stack, Tabs } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { listDownloadsOptions } from "./api/@tanstack/react-query.gen";
import { ActiveJobCard } from "./components/ActiveJobCard";
import { AppVersion } from "./components/AppVersion";
import { ConfigPanel } from "./components/ConfigPanel";
import { CountBadge } from "./components/CountBadge";
import { HealthBadge } from "./components/HealthBadge";
import { LogsPanel } from "./components/LogsPanel";
import { MaintenancePanel } from "./components/MaintenancePanel";
import { MobileMenuButton } from "./components/MobileMenuButton";
import { MobileNavDrawer } from "./components/MobileNavDrawer";
import { RecentList } from "./components/RecentList";
import { RunningJobsPanel } from "./components/RunningJobsPanel";
import { SubmitForm } from "./components/SubmitForm";
import { TargetsList } from "./components/TargetsList";
import { useEventStream } from "./lib/eventStream";
import { REFETCH_LIST_MS } from "./lib/polling";
import { isRunning, isScheduled, isTerminal, pickCurrentActiveJobId } from "./lib/status";

export default function App() {
  // Open one websocket for the app lifetime — push events into the cache so
  // lists refresh immediately on server-side state changes.
  useEventStream();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<string | null>("library");
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

  // Auto-open the "current" job (running, falling back to pending) so the
  // Jobs tab shows what's happening by default, and advance to the next
  // active job when the one we opened finishes. We only act on selections
  // we made ourselves — manual picks and explicit closes are respected.
  const lastAutoSelectedRef = useRef<number | null>(null);
  useEffect(() => {
    if (!downloads) return;
    const current = pickCurrentActiveJobId(downloads);
    if (current === null) return;

    if (selectedId === null) {
      if (lastAutoSelectedRef.current === null) {
        lastAutoSelectedRef.current = current;
        setSelectedId(current);
      }
      return;
    }

    if (selectedId === lastAutoSelectedRef.current && current !== selectedId) {
      const sel = downloads.find((d) => d.id === selectedId);
      if (sel && isTerminal(sel.status)) {
        lastAutoSelectedRef.current = current;
        setSelectedId(current);
      }
    }
  }, [downloads, selectedId]);

  const openJob = (id: number) => {
    setSelectedId(id);
    setTab("jobs");
  };

  return (
    <Box>
      <header className="app-shell-header">
        <Container size="lg">
          <div className="app-shell-header-inner">
            <div className="app-brand">
              <span className="app-brand-mark" aria-hidden="true">
                g
              </span>
              <h1 className="app-brand-word">gallery-dl-webui</h1>
              <span className="app-brand-tag" aria-hidden="true">
                archive
              </span>
            </div>
            <div className="app-shell-header-meta">
              <HealthBadge />
              <MobileMenuButton open={navOpen} onClick={() => setNavOpen((o) => !o)} />
            </div>
          </div>
        </Container>
      </header>
      <Container size="lg" py="xl" className="app-shell-body">
        <Stack gap="xl">
          <Tabs value={tab} onChange={setTab} keepMounted className="app-tabs" variant="default">
            <Tabs.List>
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
            <Tabs.Panel value="library" pt="xl">
              <Stack gap="lg">
                <SubmitForm />
                <TargetsList onOpenJob={openJob} />
              </Stack>
            </Tabs.Panel>
            <Tabs.Panel value="jobs" pt="xl">
              <JobsTabBody
                selectedId={selectedId}
                onSelect={setSelectedId}
                hasAnyActive={running > 0 || scheduled > 0}
              />
            </Tabs.Panel>
            <Tabs.Panel value="config" pt="xl">
              <ConfigPanel />
            </Tabs.Panel>
            <Tabs.Panel value="maintenance" pt="xl">
              <MaintenancePanel />
            </Tabs.Panel>
            <Tabs.Panel value="logs" pt="xl">
              {/* Only mount when active so the SSE stream is opened on demand
                  and torn down when the user navigates away. */}
              {tab === "logs" ? <LogsPanel /> : null}
            </Tabs.Panel>
          </Tabs>
          <div className="app-footnote">
            gallery-dl · webui · <AppVersion />
          </div>
        </Stack>
      </Container>
      <MobileNavDrawer
        active={tab}
        open={navOpen}
        jobsBadge={running}
        onChange={(k) => setTab(k)}
        onClose={() => setNavOpen(false)}
      />
    </Box>
  );
}

/**
 * Two-column master-detail (Direction B) on desktop. The running panel and
 * the recent list live in the left column; the active job card fills the
 * right. Under 880px both columns collapse to a single stack.
 */
function JobsTabBody({
  selectedId,
  onSelect,
  hasAnyActive,
}: {
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  hasAnyActive: boolean;
}) {
  const hasSelection = selectedId !== null;
  // On desktop with a selection, the active card sits in the right column;
  // when nothing is selected (or on mobile), the layout falls back to a
  // single column with the running and recent panels stacked.
  if (!hasSelection) {
    return (
      <Stack gap="lg">
        <RunningJobsPanel onSelect={onSelect} selectedId={selectedId} />
        <RecentList onSelect={onSelect} selectedId={selectedId} hideEmpty={!hasAnyActive} />
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
