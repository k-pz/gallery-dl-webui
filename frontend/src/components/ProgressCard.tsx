import { Badge, Box, Group, Loader, Progress, ScrollArea, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getDownloadProgressOptions } from "../api/@tanstack/react-query.gen";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { isTerminal, type Status } from "../lib/status";

export function ProgressCard({ jobId, status }: { jobId: number; status: Status }) {
  const terminal = isTerminal(status);
  const { data, isLoading } = useQuery({
    ...getDownloadProgressOptions({ path: { download_id: jobId } }),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && isTerminal(s) ? false : REFETCH_ACTIVE_MS;
    },
  });

  if (isLoading || !data) {
    return (
      <Box>
        <Text size="xs" c="dimmed" mb={4}>
          progress
        </Text>
        <Loader size="sm" />
      </Box>
    );
  }

  const expected = data.files_expected ?? 0;
  const present = data.files_present;
  const pct = expected > 0 ? (present / expected) * 100 : 0;
  const manifestReady = expected > 0 && data.chapters.length > 0;

  return (
    <Box>
      <Group justify="space-between" mb={4}>
        <Text size="xs" c="dimmed">
          progress
        </Text>
        <Text size="xs" c="dimmed">
          {manifestReady ? `${present} / ${expected} files` : "preparing…"}
        </Text>
      </Group>
      <Progress value={pct} size="md" striped={!terminal} animated={!terminal} />
      {manifestReady && (
        <ScrollArea h={220} mt="sm" type="auto">
          <Stack gap={4}>
            {data.chapters.map((ch) => {
              const done = ch.files_present === ch.files_total;
              const label = ch.name || "(root)";
              return (
                <Group key={label} justify="space-between" gap="xs" wrap="nowrap">
                  <Text
                    size="sm"
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={label}
                  >
                    {label}
                  </Text>
                  <Badge size="sm" color={done ? "green" : "blue"} variant="light">
                    {ch.files_present}/{ch.files_total}
                  </Badge>
                </Group>
              );
            })}
          </Stack>
        </ScrollArea>
      )}
    </Box>
  );
}
