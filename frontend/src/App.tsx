import { Container, Group, Stack, Tabs, Title } from "@mantine/core";
import { useState } from "react";
import { ActiveJobCard } from "./components/ActiveJobCard";
import { ConfigPanel } from "./components/ConfigPanel";
import { HealthBadge } from "./components/HealthBadge";
import { RecentList } from "./components/RecentList";
import { SubmitForm } from "./components/SubmitForm";

export default function App() {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  return (
    <Container size="md" py="xl">
      <Stack gap="md">
        <Group justify="space-between" align="flex-end">
          <Title order={1}>gallery-dl-webui</Title>
          <HealthBadge />
        </Group>
        <Tabs defaultValue="downloads" keepMounted>
          <Tabs.List>
            <Tabs.Tab value="downloads">Downloads</Tabs.Tab>
            <Tabs.Tab value="config">Config</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="downloads" pt="md">
            <Stack gap="md">
              <SubmitForm onCreated={setSelectedId} />
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
