import { Badge, Group, Loader, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getHealthOptions } from "../api/@tanstack/react-query.gen";

export function HealthBadge() {
  const { data, isLoading, error } = useQuery(getHealthOptions());
  return (
    <Group gap="xs">
      <Text size="xs" c="dimmed">
        backend
      </Text>
      {isLoading && <Loader size="xs" />}
      {data && <Badge color="green">{data.status}</Badge>}
      {error && <Badge color="red">unreachable</Badge>}
    </Group>
  );
}
