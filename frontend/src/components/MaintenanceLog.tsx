import { Box, Code, Group, Progress, ScrollArea, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getMaintenanceJobProgressOptions } from "../api/@tanstack/react-query.gen";
import { REFETCH_ACTIVE_MS } from "../lib/polling";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

export function MaintenanceLog({ jobId }: { jobId: number }) {
  const { data, isLoading } = useQuery({
    ...getMaintenanceJobProgressOptions({ path: { job_id: jobId } }),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && TERMINAL_STATUSES.has(status) ? false : REFETCH_ACTIVE_MS;
    },
  });

  if (isLoading || !data) {
    return (
      <Text size="sm" c="dimmed">
        Loading job log…
      </Text>
    );
  }

  const pct = data.total > 0 ? Math.min(100, (data.done / data.total) * 100) : 0;
  const terminal = TERMINAL_STATUSES.has(data.status);
  const counter = data.total > 0 ? `${data.done} / ${data.total}` : "preparing…";

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Job #{jobId} — {data.status}
        </Text>
        <Text size="sm" c="dimmed">
          {counter}
        </Text>
      </Group>
      <Progress value={pct} size="md" striped={!terminal} animated={!terminal} />
      <Box>
        <ScrollArea h={220} type="auto">
          <Code block style={{ fontSize: "12px" }}>
            {data.lines.length > 0 ? data.lines.join("\n") : "(no log output yet)"}
          </Code>
        </ScrollArea>
      </Box>
    </Stack>
  );
}
