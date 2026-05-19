import {
  ActionIcon,
  Anchor,
  Badge,
  Card,
  Group,
  Loader,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
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
import { isActive, statusColor } from "../lib/status";
import { formatRel } from "../lib/time";

type WatchedFilter = "any" | "watched" | "unwatched";
type StatusFilter = "any" | "completed" | "failed" | "active" | "no-runs";
type SortKey = "recent" | "name" | "created";

export function TargetsList({ onOpenJob }: { onOpenJob?: (jobId: number) => void }) {
  const { data: targets, isLoading } = useQuery({
    ...listTargetsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });
  const { data: config } = useQuery(getConfigOptions());
  const defaultPeriod = config?.default_watch_period ?? "1d";

  const [search, setSearch] = useState("");
  const [watchedFilter, setWatchedFilter] = useState<WatchedFilter>("any");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("any");
  const [extractorFilter, setExtractorFilter] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("recent");

  const extractorOptions = useMemo(() => {
    const names = new Set<string>();
    for (const t of targets ?? []) if (t.extractor) names.add(t.extractor);
    return Array.from(names).sort();
  }, [targets]);

  const visible = useMemo(() => {
    if (!targets) return [];
    const needle = search.trim().toLowerCase();
    const filtered = targets.filter((t) => {
      if (needle) {
        const haystack = `${t.name ?? ""} ${t.url}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      if (watchedFilter === "watched" && !t.watched) return false;
      if (watchedFilter === "unwatched" && t.watched) return false;
      if (extractorFilter && t.extractor !== extractorFilter) return false;
      if (statusFilter !== "any") {
        const status = t.last_status;
        const active = status !== null && isActive(status);
        if (statusFilter === "active" && !active) return false;
        if (statusFilter === "completed" && status !== "completed") return false;
        if (statusFilter === "failed" && status !== "failed") return false;
        if (statusFilter === "no-runs" && t.download_count > 0) return false;
      }
      return true;
    });
    const sorted = [...filtered];
    if (sortKey === "name") {
      sorted.sort((a, b) =>
        (a.name ?? a.url).localeCompare(b.name ?? b.url, undefined, { sensitivity: "base" }),
      );
    } else if (sortKey === "created") {
      sorted.sort((a, b) => b.created_at.localeCompare(a.created_at));
    } else {
      // recent: prefer last_finished_at; fall back to last_created_at; then created_at.
      sorted.sort((a, b) => recencyKey(b) - recencyKey(a));
    }
    return sorted;
  }, [targets, search, watchedFilter, statusFilter, extractorFilter, sortKey]);

  const totalCount = targets?.length ?? 0;
  const filtersActive =
    search.trim().length > 0 ||
    watchedFilter !== "any" ||
    statusFilter !== "any" ||
    extractorFilter !== null;

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Group justify="space-between" align="center" wrap="wrap">
          <Group gap="xs" align="center">
            <Title order={3}>Library</Title>
            {totalCount > 0 && (
              <Text size="sm" c="dimmed">
                {filtersActive
                  ? `${visible.length} of ${totalCount}`
                  : `${totalCount} ${totalCount === 1 ? "series" : "series"}`}
              </Text>
            )}
          </Group>
          {isLoading && <Loader size="xs" />}
        </Group>
        {totalCount > 0 && (
          <Stack gap="xs">
            <Group gap="xs" align="flex-end" wrap="wrap">
              <TextInput
                placeholder="Search name or URL"
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
                style={{ flex: 1, minWidth: 200 }}
                aria-label="Filter library by name or URL"
              />
              <Select
                label="Status"
                data={[
                  { value: "any", label: "Any" },
                  { value: "completed", label: "Completed" },
                  { value: "failed", label: "Failed" },
                  { value: "active", label: "Active" },
                  { value: "no-runs", label: "Never run" },
                ]}
                value={statusFilter}
                onChange={(v) => setStatusFilter((v as StatusFilter) ?? "any")}
                w={140}
                comboboxProps={{ withinPortal: true }}
              />
              <Select
                label="Extractor"
                data={[
                  { value: "", label: "Any" },
                  ...extractorOptions.map((e) => ({ value: e, label: e })),
                ]}
                value={extractorFilter ?? ""}
                onChange={(v) => setExtractorFilter(v ? v : null)}
                w={160}
                comboboxProps={{ withinPortal: true }}
                disabled={extractorOptions.length === 0}
              />
              <Select
                label="Sort by"
                data={[
                  { value: "recent", label: "Last downloaded" },
                  { value: "name", label: "Name" },
                  { value: "created", label: "Added" },
                ]}
                value={sortKey}
                onChange={(v) => setSortKey((v as SortKey) ?? "recent")}
                w={170}
                comboboxProps={{ withinPortal: true }}
              />
            </Group>
            <SegmentedControl
              value={watchedFilter}
              onChange={(v) => setWatchedFilter(v as WatchedFilter)}
              data={[
                { value: "any", label: "All" },
                { value: "watched", label: "Watched" },
                { value: "unwatched", label: "Unwatched" },
              ]}
              size="xs"
            />
          </Stack>
        )}
        {totalCount === 0 && (
          <Text size="sm" c="dimmed">
            No targets yet. Submit a gallery URL above to add one.
          </Text>
        )}
        {totalCount > 0 && visible.length === 0 && (
          <Text size="sm" c="dimmed">
            No series match the current filters.
          </Text>
        )}
        {visible.length > 0 && (
          <Stack gap="sm">
            {visible.map((t) => (
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

function recencyKey(t: TargetOut): number {
  const candidates = [t.last_finished_at, t.last_created_at, t.created_at];
  for (const v of candidates) {
    if (!v) continue;
    const n = Date.parse(v);
    if (!Number.isNaN(n)) return n;
  }
  return 0;
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
  const displayName = target.name ?? target.url;
  const showUrlSubtitle = Boolean(target.name);

  return (
    <Card withBorder padding="sm" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text fw={600} style={{ wordBreak: "break-word" }}>
              {displayName}
            </Text>
            {showUrlSubtitle && (
              <Anchor
                href={target.url}
                target="_blank"
                rel="noreferrer"
                size="xs"
                c="dimmed"
                style={{ wordBreak: "break-all" }}
              >
                {target.url}
              </Anchor>
            )}
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
                Last downloaded: {formatRel(target.last_finished_at)}
              </Text>
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
                  if (confirm(`Remove ${displayName} from the library?`)) {
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
