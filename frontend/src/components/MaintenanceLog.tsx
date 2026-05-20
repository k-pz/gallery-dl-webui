import { Badge, Box, Group, Progress, ScrollArea, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getMaintenanceJobProgressOptions } from "../api/@tanstack/react-query.gen";
import { REFETCH_ACTIVE_MS } from "../lib/polling";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

const STATUS_COLOR: Record<string, string> = {
  pending: "gray",
  running: "blue",
  completed: "green",
  failed: "red",
  cancelled: "orange",
};

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
    <Stack gap="sm">
      <Group justify="space-between" align="center" wrap="wrap">
        <Group gap="xs" align="center">
          <span className="app-section-kicker">log</span>
          <Text size="sm" c="dimmed" ff="monospace">
            Job #{jobId}
          </Text>
          <Badge color={STATUS_COLOR[data.status] ?? "gray"} variant="light" size="sm">
            {data.status}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed" ff="monospace">
          {counter}
        </Text>
      </Group>
      <Progress value={pct} size="md" radius="sm" striped={!terminal} animated={!terminal} />
      <Box
        style={{
          border: "1px solid var(--app-border-subtle)",
          borderRadius: "var(--mantine-radius-md)",
          background: "var(--app-surface-muted)",
          overflow: "hidden",
        }}
      >
        <ScrollArea h={240} type="auto">
          <Box
            component="pre"
            m={0}
            p="md"
            style={{
              fontFamily: "var(--app-mono)",
              fontSize: "0.78rem",
              lineHeight: 1.55,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: "var(--app-text-muted)",
            }}
          >
            {data.lines.length > 0 ? data.lines.join("\n") : "(no log output yet)"}
          </Box>
        </ScrollArea>
      </Box>
    </Stack>
  );
}
