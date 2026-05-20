import {
  ActionIcon,
  Anchor,
  Badge,
  Box,
  Card,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  deleteTargetMutation,
  getConfigOptions,
  listTargetsOptions,
  pollTargetMutation,
  updateTargetMutation,
} from "../api/@tanstack/react-query.gen";
import type { TargetOut } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { makeNeedleMatcher } from "../lib/listFilters";
import { usePagination } from "../lib/pagination";
import { REFETCH_LIST_MS } from "../lib/polling";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { isActive, jobStatusLabel, statusColor } from "../lib/status";
import { formatRel } from "../lib/time";
import { ListHeader } from "./ListHeader";
import { ListPagination } from "./ListPagination";
import { ListToolbar } from "./ListToolbar";
import { type SortDir, SortDirToggle } from "./SortDirToggle";

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
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const extractorOptions = useMemo(() => {
    const names = new Set<string>();
    for (const t of targets ?? []) if (t.extractor) names.add(t.extractor);
    return Array.from(names).sort();
  }, [targets]);

  const visible = useMemo(() => {
    if (!targets) return [];
    const matchesNeedle = makeNeedleMatcher<TargetOut>(
      search,
      (t) => t.name,
      (t) => t.url,
    );
    const filtered = targets.filter((t) => {
      if (!matchesNeedle(t)) return false;
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
    const dir = sortDir === "asc" ? 1 : -1;
    if (sortKey === "name") {
      sorted.sort(
        (a, b) =>
          dir *
          (a.name ?? a.url).localeCompare(b.name ?? b.url, undefined, { sensitivity: "base" }),
      );
    } else if (sortKey === "created") {
      sorted.sort((a, b) => dir * a.created_at.localeCompare(b.created_at));
    } else {
      sorted.sort((a, b) => dir * (recencyKey(a) - recencyKey(b)));
    }
    return sorted;
  }, [targets, search, watchedFilter, statusFilter, extractorFilter, sortKey, sortDir]);

  const totalCount = targets?.length ?? 0;
  const filtersActive =
    search.trim().length > 0 ||
    watchedFilter !== "any" ||
    statusFilter !== "any" ||
    extractorFilter !== null;

  const pagination = usePagination(
    visible,
    `${search}|${watchedFilter}|${statusFilter}|${extractorFilter ?? ""}|${sortKey}|${sortDir}`,
  );

  return (
    <Card>
      <Stack gap="md">
        <Stack gap={4}>
          <span className="app-section-kicker">library</span>
          <ListHeader
            title="Series"
            titleOrder={3}
            totalCount={totalCount}
            visibleCount={visible.length}
            filtersActive={filtersActive}
            isLoading={isLoading}
            formatTotal={(n) => `${n} series`}
          />
        </Stack>
        {totalCount > 0 && (
          <ListToolbar
            search={search}
            setSearch={setSearch}
            searchPlaceholder="Search name or URL"
            searchAriaLabel="Filter library by name or URL"
            searchMinWidth={200}
            belowChildren={
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
            }
          >
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
            <Group gap={4} align="flex-end" wrap="nowrap">
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
              <SortDirToggle dir={sortDir} sortKey={sortKey} onToggle={setSortDir} />
            </Group>
          </ListToolbar>
        )}
        {totalCount === 0 && (
          <EmptyHint>
            Your library is empty. Submit a gallery URL above to start tracking a series.
          </EmptyHint>
        )}
        {totalCount > 0 && visible.length === 0 && (
          <EmptyHint>No series match the current filters.</EmptyHint>
        )}
        {visible.length > 0 && (
          <Stack gap={0}>
            {pagination.pageItems.map((t, i) => (
              <TargetRow
                key={t.id}
                target={t}
                defaultPeriod={defaultPeriod}
                onOpenJob={onOpenJob}
                divider={i > 0}
              />
            ))}
          </Stack>
        )}
        <ListPagination
          page={pagination.page}
          setPage={pagination.setPage}
          totalPages={pagination.totalPages}
          start={pagination.start}
          end={pagination.end}
          total={pagination.total}
          ariaLabel="Library pagination"
        />
      </Stack>
    </Card>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <Box
      style={{
        padding: "1.5rem 1rem",
        textAlign: "center",
        border: "1px dashed var(--app-border-subtle)",
        borderRadius: "var(--mantine-radius-md)",
        background: "var(--app-surface-muted)",
      }}
    >
      <Text size="sm" c="dimmed">
        {children}
      </Text>
    </Box>
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
  divider,
}: {
  target: TargetOut;
  defaultPeriod: string;
  onOpenJob?: (jobId: number) => void;
  divider: boolean;
}) {
  const invalidate = useDataInvalidators();
  const [period, setPeriod] = useState(target.watch_period ?? "");
  const [periodDirty, setPeriodDirty] = useState(false);
  const [periodError, setPeriodError] = useState<string | null>(null);

  useEffect(() => {
    if (!periodDirty) setPeriod(target.watch_period ?? "");
  }, [target.watch_period, periodDirty]);

  const update = useMutation({
    ...updateTargetMutation(),
    onSuccess: () => {
      setPeriodDirty(false);
      setPeriodError(null);
      invalidate.targets();
    },
    onError: (err) => setPeriodError(extractErrorMessage(err)),
  });

  const poll = useMutation({
    ...pollTargetMutation(),
    onSuccess: () => {
      notifications.show({
        title: "Poll queued",
        message: `Queued a fresh job for ${target.url}`,
        color: "blue",
      });
      invalidate.targets();
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
      invalidate.targets();
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
    <Stack
      gap="sm"
      py="md"
      style={{
        borderTop: divider ? "1px solid var(--app-border-subtle)" : undefined,
      }}
    >
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
          <Group gap="xs" wrap="wrap" align="center">
            <Badge color={statusColor(status)} variant="light" size="sm">
              {jobStatusLabel(status)}
            </Badge>
            <Text fw={600} size="md" style={{ wordBreak: "break-word" }}>
              {displayName}
            </Text>
          </Group>
          {showUrlSubtitle && (
            <Anchor href={target.url} target="_blank" rel="noreferrer" className="app-url">
              {target.url}
            </Anchor>
          )}
          <Group gap="md" wrap="wrap" mt={2}>
            <MetaLabel label="Extractor" value={target.extractor ?? "—"} mono />
            <MetaLabel
              label="Runs"
              value={`${target.download_count}${target.download_count === 1 ? " run" : " runs"}`}
            />
            <MetaLabel label="Last run" value={formatRel(target.last_finished_at) ?? "—"} />
            {target.last_download_id !== null && onOpenJob && (
              <Anchor
                size="xs"
                component="button"
                type="button"
                onClick={() =>
                  target.last_download_id !== null && onOpenJob(target.last_download_id)
                }
              >
                open job #{target.last_download_id} →
              </Anchor>
            )}
          </Group>
        </Stack>
        <Group gap="xs" wrap="nowrap">
          <Tooltip label="Poll now" withArrow>
            <ActionIcon
              variant="light"
              color="amber"
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
      <Group gap="md" align="flex-end" wrap="wrap">
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
              ? "Per-target override. Clear to fall back."
              : `Default: ${defaultPeriod}`
          }
          w={170}
          error={periodError ?? undefined}
        />
        <Select
          label="Reading direction"
          value={target.reading_direction ?? ""}
          data={[{ value: "", label: "Use default" }, ...READING_DIRECTION_OPTIONS]}
          onChange={(v) =>
            update.mutate({
              path: { target_id: target.id },
              body: { reading_direction: v ?? "" },
            })
          }
          disabled={update.isPending}
          w={180}
          comboboxProps={{ withinPortal: true }}
          allowDeselect={false}
        />
      </Group>
      <TagsInput
        label="Tags"
        placeholder="Enter to add"
        value={target.tags}
        onChange={(next) =>
          update.mutate({
            path: { target_id: target.id },
            body: { tags: next },
          })
        }
        disabled={update.isPending}
        clearable
      />
    </Stack>
  );
}

function MetaLabel({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <Text size="xs" c="dimmed" component="span">
      <Text span fz="xs" c="dimmed" style={{ letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {label}
      </Text>
      {"  "}
      <Text span fz="xs" c="var(--app-text-muted)" ff={mono ? "monospace" : undefined}>
        {value}
      </Text>
    </Text>
  );
}
