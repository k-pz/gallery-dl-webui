import { Badge, Card, Container, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getHealthOptions } from "./api/@tanstack/react-query.gen";

function App() {
  const { data, isLoading, error } = useQuery(getHealthOptions());

  return (
    <Container size="sm" py="xl">
      <Stack gap="md">
        <Title order={1}>gallery-dl-webui</Title>
        <Card withBorder shadow="sm" padding="lg">
          <Group justify="space-between" mb="xs">
            <Text fw={500}>Backend</Text>
            {isLoading && <Loader size="xs" />}
            {data && <Badge color="green">{data.status}</Badge>}
            {error && <Badge color="red">unreachable</Badge>}
          </Group>
          <Text size="sm" c="dimmed">
            GET /api/health
          </Text>
        </Card>
      </Stack>
    </Container>
  );
}

export default App;
