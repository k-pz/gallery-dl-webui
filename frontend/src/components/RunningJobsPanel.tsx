import { Box, Button, Card, Group, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { listDownloadsOptions } from "../api/@tanstack/react-query.gen";
import type { Download } from "../api/types.gen";
import { useEta } from "../hooks/useEta";
import { useCancelAllDownloads } from "../lib/downloadActions";
import { downloadEtaDimension, formatEta } from "../lib/eta";
import { REFETCH_LIST_MS } from "../lib/polling";
import {
  isCancellable,
  isRunning,
  isScheduled,
  isTerminal,
  jobStep,
  statusTone,
} from "../lib/status";
import { IconX } from "./Icons";
import { InlineConfirm } from "./InlineConfirm";
import { Pill } from "./Pill";

function progressLabel(item: Download): string {
  const total = item.chapters_total;
  if (total != null) {
    const packed = item.postprocess_chapters_packed;
    if (packed != null) return `${packed}/${total} chapters`;
    return `${total} chapters`;
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
  const [confirmingCancelAll, setConfirmingCancelAll] = useState(false);
  const cancelAll = useCancelAllDownloads();

  const { running, scheduledCount, cancellableIds } = useMemo(() => {
    const list = data ?? [];
    const r = list.filter((d) => isRunning(d.status)).sort((a, b) => a.id - b.id);
    const s = list.filter((d) => isScheduled(d.status)).length;
    const c = list.filter((d) => isCancellable(d.status)).map((d) => d.id);
    return { running: r, scheduledCount: s, cancellableIds: c };
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
          {cancellableIds.length > 1 && !confirmingCancelAll && (
            <Button
              size="xs"
              variant="light"
              color="red"
              leftSection={<IconX size={14} />}
              loading={cancelAll.isPending}
              onClick={() => setConfirmingCancelAll(true)}
            >
              Cancel all
            </Button>
          )}
        </Group>
        {confirmingCancelAll && (
          <InlineConfirm
            confirmLabel="Cancel all"
            cancelLabel="Keep running"
            message={
              <>
                Cancel all <strong>{cancellableIds.length}</strong> active and scheduled jobs?
                Completed chapters stay on disk; requeue any job later to resume.
              </>
            }
            loading={cancelAll.isPending}
            onCancel={() => setConfirmingCancelAll(false)}
            onConfirm={() =>
              cancelAll.mutate(cancellableIds, {
                onSettled: () => setConfirmingCancelAll(false),
              })
            }
          />
        )}
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
  const showUrlSubtitle = Boolean(item.name);
  const dim = downloadEtaDimension(item);
  const eta = useEta({
    resetKey: `dl:${item.id}:${dim.phaseKey}`,
    startedAt: item.started_at,
    done: dim.done,
    total: dim.total,
    active: !isTerminal(item.status),
  });
  return (
    <Box className="app-row" data-selected={selected ? "true" : undefined}>
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <div className="app-row-line">
          <Pill tone={statusTone(item.status)}>{step.label}</Pill>
          <Text size="xs" c="dimmed" ff="monospace">
            #{item.id}
          </Text>
          {/* Real <button> whose ::after covers the row — see .app-row-select. */}
          <Text
            component="button"
            type="button"
            className="app-row-name app-row-select"
            size="sm"
            fw={selected ? 600 : 500}
            title={displayName}
            onClick={() => onSelect(item.id)}
          >
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
        {showUrlSubtitle && (
          <Text className="app-url app-row-url" title={item.url}>
            {item.url}
          </Text>
        )}
      </Stack>
    </Box>
  );
}
