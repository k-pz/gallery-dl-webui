import {
  ActionIcon,
  Anchor,
  Badge,
  Card,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  deleteTargetMutation,
  getConfigOptions,
  listTargetsOptions,
  listTargetsQueryKey,
  pollTargetMutation,
  updateTargetMutation,
} from "../api/@tanstack/react-query.gen";
import type { TargetOut } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import { REFETCH_LIST_MS } from "../lib/polling";
import { statusColor } from "../lib/status";

export function TargetsList({ onOpenJob }: { onOpenJob?: (jobId: number) => void }) {
  const { data: targets, isLoading } = useQuery({
    ...listTargetsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });
  const { data: config } = useQuery(getConfigOptions());
  const defaultPeriod = config?.default_watch_period ?? "1d";

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={3}>Library</Title>
          {isLoading && <Loader size="xs" />}
        </Group>
        {targets && targets.length === 0 && (
          <Text size="sm" c="dimmed">
            No targets yet. Submit a gallery URL above to add one.
          </Text>
        )}
        {targets && targets.length > 0 && (
          <Stack gap="sm">
            {targets.map((t) => (
              <TargetRow
                key={t.id}
                target={t}
                defaultPeriod={defaultPeriod}
                onOpenJob={onOpenJob}
              />
            ))}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}

function TargetRow({
  target,
  defaultPeriod,
  onOpenJob,
}: {
  target: TargetOut;
  defaultPeriod: string;
  onOpenJob?: (jobId: number) => void;
}) {
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState(target.watch_period ?? "");
  const [periodDirty, setPeriodDirty] = useState(false);
  const [periodError, setPeriodError] = useState<string | null>(null);

  // Reset local period state when the upstream value changes (e.g. another tab edited it).
  useEffect(() => {
    if (!periodDirty) setPeriod(target.watch_period ?? "");
  }, [target.watch_period, periodDirty]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: listTargetsQueryKey() });
  };

  const update = useMutation({
    ...updateTargetMutation(),
    onSuccess: () => {
      setPeriodDirty(false);
      setPeriodError(null);
      invalidate();
    },
    onError: (err) => setPeriodError(extractErrorMessage(err)),
  });

  const poll = useMutation({
    ...pollTargetMutation(),
    onSuccess: () => {
      notifications.show({
        title: "Polling",
        message: `Queued a fresh download for ${target.url}`,
        color: "blue",
      });
      invalidate();
    },
    onError: (err) =>
      notifications.show({
        title: "Poll failed",
        message: extractErrorMessage(err),
        color: "red",
      }),
  });

  const del = useMutation({
    ...deleteTargetMutation(),
    onSuccess: () => {
      notifications.show({
        title: "Target removed",
        message: target.url,
        color: "gray",
      });
      invalidate();
    },
    onError: (err) =>
      notifications.show({
        title: "Delete failed",
        message: extractErrorMessage(err),
        color: "red",
      }),
  });

  const submitPeriod = () => {
    if (!periodDirty) return;
    update.mutate({
      path: { target_id: target.id },
      body: { watch_period: period },
    });
  };

  const status = target.last_status ?? "pending";
  const busy = update.isPending || poll.isPending || del.isPending;

  return (
    <Card withBorder padding="sm" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text fw={500} style={{ wordBreak: "break-all" }}>
              {target.url}
            </Text>
            <Group gap="xs">
              <Badge color={statusColor(status)} variant="light" size="sm">
                {status}
              </Badge>
              <Text size="xs" c="dimmed">
                {target.extractor ?? "—"}
              </Text>
              <Text size="xs" c="dimmed">
                {target.download_count} run{target.download_count === 1 ? "" : "s"}
              </Text>
              <Text size="xs" c="dimmed">
                last: {formatRel(target.last_finished_at ?? target.last_created_at)}
              </Text>
              {target.last_polled_at && (
                <Text size="xs" c="dimmed">
                  polled: {formatRel(target.last_polled_at)}
                </Text>
              )}
              {target.last_download_id !== null && onOpenJob && (
                <Anchor
                  size="xs"
                  component="button"
                  type="button"
                  onClick={() =>
                    target.last_download_id !== null && onOpenJob(target.last_download_id)
                  }
                >
                  open job #{target.last_download_id}
                </Anchor>
              )}
            </Group>
          </Stack>
          <Group gap="xs" wrap="nowrap">
            <Tooltip label="Poll now" withArrow>
              <ActionIcon
                variant="light"
                color="blue"
                disabled={busy}
                loading={poll.isPending}
                onClick={() => poll.mutate({ path: { target_id: target.id } })}
                aria-label={`Poll target ${target.id}`}
              >
                ▶
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Remove from library" withArrow>
              <ActionIcon
                variant="subtle"
                color="red"
                disabled={busy}
                loading={del.isPending}
                onClick={() => {
                  if (confirm(`Remove ${target.url} from the library?`)) {
                    del.mutate({ path: { target_id: target.id } });
                  }
                }}
                aria-label={`Delete target ${target.id}`}
              >
                ✕
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
        <Group gap="md" align="center" wrap="wrap">
          <Switch
            label="Watch"
            checked={target.watched}
            disabled={update.isPending}
            onChange={(e) =>
              update.mutate({
                path: { target_id: target.id },
                body: { watched: e.currentTarget.checked },
              })
            }
          />
          <TextInput
            label="Poll every"
            placeholder={defaultPeriod}
            value={period}
            disabled={!target.watched || update.isPending}
            onChange={(e) => {
              setPeriod(e.currentTarget.value);
              setPeriodDirty(true);
            }}
            onBlur={submitPeriod}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitPeriod();
            }}
            description={
              target.watch_period
                ? "Per-target override. Clear to fall back to default."
                : `Default: ${defaultPeriod}`
            }
            w={170}
            error={periodError ?? undefined}
          />
        </Group>
      </Stack>
    </Card>
  );
}

function formatRel(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(t).toLocaleDateString();
}
