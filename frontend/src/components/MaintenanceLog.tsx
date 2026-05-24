import {
  Badge,
  Box,
  Group,
  Progress,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getMaintenanceJobProgressOptions } from "../api/@tanstack/react-query.gen";
import { useEta } from "../hooks/useEta";
import { formatEta } from "../lib/eta";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { IconChevronDown } from "./Icons";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

const STATUS_COLOR: Record<string, string> = {
  pending: "gray",
  running: "blue",
  completed: "green",
  failed: "red",
  cancelled: "orange",
};

export function MaintenanceLog({
  jobId,
  startedAt,
}: {
  jobId: number;
  startedAt: string | null | undefined;
}) {
  const { data, isLoading } = useQuery({
    ...getMaintenanceJobProgressOptions({ path: { job_id: jobId } }),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && TERMINAL_STATUSES.has(status) ? false : REFETCH_ACTIVE_MS;
    },
  });
  const [expanded, setExpanded] = useState(false);

  const terminal = data ? TERMINAL_STATUSES.has(data.status) : false;
  const eta = useEta({
    resetKey: `maint:${jobId}`,
    startedAt,
    done: data?.done ?? 0,
    total: data && data.total > 0 ? data.total : null,
    active: !!data && !terminal,
  });

  if (isLoading || !data) {
    return (
      <Text size="sm" c="dimmed">
        Loading job log…
      </Text>
    );
  }

  const pct = data.total > 0 ? Math.min(100, (data.done / data.total) * 100) : 0;
  let counter: string;
  if (data.total <= 0) counter = "preparing…";
  else if (eta.kind === "eta")
    counter = `~${formatEta(eta.remainingMs)} · ${data.done} / ${data.total}`;
  else counter = `${data.done} / ${data.total}`;

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
        <Group gap="sm" align="center">
          <Text size="sm" c="dimmed" ff="monospace">
            {counter}
          </Text>
          <UnstyledButton
            className="maint-log-toggle"
            onClick={() => setExpanded((e) => !e)}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse job log" : "Expand job log"}
            data-expanded={expanded ? "true" : undefined}
          >
            <Text size="xs" c="dimmed" ff="monospace">
              {expanded ? "collapse" : "expand"}
            </Text>
            <IconChevronDown size={14} className="maint-log-toggle-chev" />
          </UnstyledButton>
        </Group>
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
        <ScrollArea h={expanded ? "70vh" : 240} type="auto">
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
