import { Container, Group, Stack, Title } from "@mantine/core";
import { useState } from "react";
import { ActiveJobCard } from "./components/ActiveJobCard";
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
        <SubmitForm onCreated={setSelectedId} />
        {selectedId !== null && <ActiveJobCard jobId={selectedId} />}
        <RecentList onSelect={setSelectedId} selectedId={selectedId} />
      </Stack>
    </Container>
  );
}
