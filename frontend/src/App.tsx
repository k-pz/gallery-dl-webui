import { Box, Container, Stack, Tabs } from "@mantine/core";
import { useState } from "react";
import { ActiveJobCard } from "./components/ActiveJobCard";
import { ConfigPanel } from "./components/ConfigPanel";
import { HealthBadge } from "./components/HealthBadge";
import { MaintenancePanel } from "./components/MaintenancePanel";
import { RecentList } from "./components/RecentList";
import { SubmitForm } from "./components/SubmitForm";
import { TargetsList } from "./components/TargetsList";
import { useEventStream } from "./lib/eventStream";

export default function App() {
  // Open one websocket for the app lifetime — push events into the cache so
  // lists refresh immediately on server-side state changes.
  useEventStream();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<string | null>("library");

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
            <HealthBadge />
          </div>
        </Container>
      </header>
      <Container size="lg" py="xl">
        <Stack gap="xl">
          <Tabs value={tab} onChange={setTab} keepMounted className="app-tabs" variant="default">
            <Tabs.List>
              <Tabs.Tab value="library">Library</Tabs.Tab>
              <Tabs.Tab value="jobs">Jobs</Tabs.Tab>
              <Tabs.Tab value="config">Config</Tabs.Tab>
              <Tabs.Tab value="maintenance">Maintenance</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="library" pt="xl">
              <Stack gap="lg">
                <SubmitForm />
                <TargetsList onOpenJob={openJob} />
              </Stack>
            </Tabs.Panel>
            <Tabs.Panel value="jobs" pt="xl">
              <Stack gap="lg">
                {selectedId !== null && <ActiveJobCard jobId={selectedId} />}
                <RecentList onSelect={setSelectedId} selectedId={selectedId} />
              </Stack>
            </Tabs.Panel>
            <Tabs.Panel value="config" pt="xl">
              <ConfigPanel />
            </Tabs.Panel>
            <Tabs.Panel value="maintenance" pt="xl">
              <MaintenancePanel />
            </Tabs.Panel>
          </Tabs>
          <div className="app-footnote">gallery-dl · webui</div>
        </Stack>
      </Container>
    </Box>
  );
}
