import { Box, Card, Group, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { listDownloadsOptions } from "../api/@tanstack/react-query.gen";
import type { Download } from "../api/types.gen";
import { useEta } from "../hooks/useEta";
import { downloadEtaDimension, formatEta } from "../lib/eta";
import { REFETCH_LIST_MS } from "../lib/polling";
import { isRunning, isScheduled, isTerminal, jobStep, statusTone } from "../lib/status";
import { Pill } from "./Pill";

function progressLabel(item: Download): string {
  const total = item.chapters_total;
  if (total != null) {
    const packed = item.postprocess_chapters_packed;
    if (packed != null) return `${packed}/${total} ch.`;
    return `${total} ch.`;
  }
  if (item.files_expected != null) {
    return `${item.files_downloaded}/${item.files_expected}`;
  }
  if (item.files_downloaded > 0) return `${item.files_downloaded} files`;
  return "—";
}

export function RunningJobsPanel({
  onSelect,
  selectedId,
}: {
  onSelect: (id: number) => void;
  selectedId: number | null;
}) {
  const { data } = useQuery({
    ...listDownloadsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });

  const { running, scheduledCount } = useMemo(() => {
    const list = data ?? [];
    const r = list.filter((d) => isRunning(d.status)).sort((a, b) => a.id - b.id);
    const s = list.filter((d) => isScheduled(d.status)).length;
    return { running: r, scheduledCount: s };
  }, [data]);

  if (running.length === 0 && scheduledCount === 0) return null;

  return (
    <Card>
      <Stack gap="md">
        <Group justify="space-between" align="center" wrap="wrap">
          <Stack gap={4}>
            <span className="app-section-kicker">now</span>
            <Text size="sm" c="dimmed" ff="monospace">
              {running.length} running · {scheduledCount} scheduled
            </Text>
          </Stack>
        </Group>
        {running.length === 0 ? (
          <Text size="sm" c="dimmed">
            Nothing running. {scheduledCount} job{scheduledCount === 1 ? "" : "s"} queued.
          </Text>
        ) : (
          <Stack gap={2}>
            {running.map((item) => (
              <RunningRow
                key={item.id}
                item={item}
                selected={item.id === selectedId}
                onSelect={onSelect}
              />
            ))}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}

function RunningRow({
  item,
  selected,
  onSelect,
}: {
  item: Download;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  const step = jobStep(item.status, item.postprocess_status, false);
  const displayName = item.name ?? item.url;
  const dim = downloadEtaDimension(item);
  const eta = useEta({
    resetKey: `dl:${item.id}:${dim.phaseKey}`,
    startedAt: item.started_at,
    done: dim.done,
    total: dim.total,
    active: !isTerminal(item.status),
  });
  return (
    <Box
      className="app-row"
      data-selected={selected ? "true" : undefined}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(item.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(item.id);
        }
      }}
    >
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <div className="app-row-line">
          <Pill tone={statusTone(item.status)}>{step.label}</Pill>
          <Text size="xs" c="dimmed" ff="monospace">
            #{item.id}
          </Text>
          <Text className="app-row-name" size="sm" fw={selected ? 600 : 500} title={displayName}>
            {displayName}
          </Text>
          {eta.kind === "eta" && (
            <Text
              size="xs"
              c="dimmed"
              ff="monospace"
              style={{ whiteSpace: "nowrap" }}
              title="Estimated time remaining"
            >
              ~{formatEta(eta.remainingMs)}
            </Text>
          )}
          <Text size="xs" c="dimmed" ff="monospace" style={{ whiteSpace: "nowrap" }}>
            {progressLabel(item)}
          </Text>
        </div>
      </Stack>
    </Box>
  );
}
