import { Badge, Card, Group, List, Loader, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { listDownloadsOptions } from "../api/@tanstack/react-query.gen";
import { REFETCH_LIST_MS } from "../lib/polling";
import { statusColor } from "../lib/status";

export function RecentList({
  onSelect,
  selectedId,
}: {
  onSelect: (id: number) => void;
  selectedId: number | null;
}) {
  const { data, isLoading } = useQuery({
    ...listDownloadsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="xs">
        <Title order={4}>Recent</Title>
        {isLoading && <Loader size="xs" />}
        {data && data.length === 0 && (
          <Text size="sm" c="dimmed">
            No downloads yet.
          </Text>
        )}
        {data && data.length > 0 && (
          <List spacing="xs" listStyleType="none" withPadding={false}>
            {data.map((item) => (
              <List.Item key={item.id}>
                <Group
                  gap="sm"
                  wrap="nowrap"
                  style={{
                    cursor: "pointer",
                    fontWeight: item.id === selectedId ? 600 : 400,
                  }}
                  onClick={() => onSelect(item.id)}
                >
                  <Badge color={statusColor(item.status)} variant="light">
                    {item.status}
                  </Badge>
                  <Text
                    size="sm"
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      flex: 1,
                    }}
                    title={item.url}
                  >
                    #{item.id} {item.url}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {item.files_downloaded}/{item.files_expected ?? "?"}
                  </Text>
                </Group>
              </List.Item>
            ))}
          </List>
        )}
      </Stack>
    </Card>
  );
}
