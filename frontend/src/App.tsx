import { Container, Group, Stack, Tabs, Title } from "@mantine/core";
import { useState } from "react";
import { ActiveJobCard } from "./components/ActiveJobCard";
import { ConfigPanel } from "./components/ConfigPanel";
import { HealthBadge } from "./components/HealthBadge";
import { RecentList } from "./components/RecentList";
import { SubmitForm } from "./components/SubmitForm";
import { TargetsList } from "./components/TargetsList";

export default function App() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<string | null>("library");

  const openJob = (id: number) => {
    setSelectedId(id);
    setTab("jobs");
  };

  return (
    <Container size="md" py="xl">
      <Stack gap="md">
        <Group justify="space-between" align="flex-end">
          <Title order={1}>gallery-dl-webui</Title>
          <HealthBadge />
        </Group>
        <Tabs value={tab} onChange={setTab} keepMounted>
          <Tabs.List>
            <Tabs.Tab value="library">Library</Tabs.Tab>
            <Tabs.Tab value="jobs">Jobs</Tabs.Tab>
            <Tabs.Tab value="config">Config</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="library" pt="md">
            <Stack gap="md">
              <SubmitForm />
              <TargetsList onOpenJob={openJob} />
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="jobs" pt="md">
            <Stack gap="md">
              {selectedId !== null && <ActiveJobCard jobId={selectedId} />}
              <RecentList onSelect={setSelectedId} selectedId={selectedId} />
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="config" pt="md">
            <ConfigPanel />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Container>
  );
}
