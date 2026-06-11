import { Button, Card, Group, SegmentedControl, Select, Stack, Tooltip } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  getConfigOptions,
  listTargetsOptions,
  pollWatchedTargetsMutation,
} from "../api/@tanstack/react-query.gen";
import type { Target } from "../api/types.gen";
import { useDataInvalidators } from "../lib/invalidate";
import { makeNeedleMatcher } from "../lib/listFilters";
import { usePagination } from "../lib/pagination";
import { REFETCH_LIST_MS } from "../lib/polling";
import { FINISHED_SERIES_STATUSES } from "../lib/seriesStatus";
import { isActive } from "../lib/status";
import { useNotifyingMutation } from "../lib/useNotifyingMutation";
import { EmptyState } from "./EmptyState";
import { ICON_SIZE, IconLibrary, IconRefresh } from "./Icons";
import { ListHeader } from "./ListHeader";
import { ListPagination } from "./ListPagination";
import { ListToolbar } from "./ListToolbar";
import { type SortDir, SortDirToggle } from "./SortDirToggle";
import { recencyKey, TargetRow } from "./TargetRow";

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
  const invalidate = useDataInvalidators();

  const refreshWatched = useNotifyingMutation(
    {
      ...pollWatchedTargetsMutation(),
      onSuccess: () => {
        invalidate.targets();
        invalidate.downloads();
      },
    },
    {
      success: {
        title: "Refresh scheduled",
        message: (res) =>
          res.skipped_active > 0
            ? `${res.scheduled} series queued · ${res.skipped_active} skipped (already downloading)`
            : `${res.scheduled} series queued`,
        color: "blue",
      },
      error: { title: "Refresh failed" },
    },
  );

  // Mirrors the backend's poll-watched eligibility so the button can disable
  // itself when a refresh would be a no-op.
  const refreshableCount = useMemo(
    () =>
      (targets ?? []).filter(
        (t) => t.watched && !FINISHED_SERIES_STATUSES.includes(t.series_status ?? ""),
      ).length,
    [targets],
  );

  const [search, setSearch] = useState("");
  const [watchedFilter, setWatchedFilter] = useState<WatchedFilter>("any");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("any");
  const [extractorFilter, setExtractorFilter] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("recent");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const extractorOptions = useMemo(() => {
    const names = new Set<string>();
    for (const t of targets ?? []) if (t.extractor) names.add(t.extractor);
    return Array.from(names).sort();
  }, [targets]);

  const visible = useMemo(() => {
    if (!targets) return [];
    const matchesNeedle = makeNeedleMatcher<Target>(
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
        const active = status != null && isActive(status);
        if (statusFilter === "active" && !active) return false;
        if (statusFilter === "completed" && status !== "completed") return false;
        if (statusFilter === "failed" && status !== "failed") return false;
        if (statusFilter === "no-runs" && (t.download_count ?? 0) > 0) return false;
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
            actions={
              totalCount > 0 && (
                <Tooltip
                  label={
                    refreshableCount === 0
                      ? "No watched series are expecting chapters right now"
                      : "Schedule a sync for every watched series still expecting chapters"
                  }
                  withArrow
                >
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<IconRefresh size={ICON_SIZE.sm} />}
                    loading={refreshWatched.isPending}
                    // aria-disabled (not native disabled) keeps the button
                    // hoverable so the tooltip can explain *why* it's inert;
                    // the click is guarded below.
                    aria-disabled={refreshableCount === 0 || undefined}
                    data-disabled={refreshableCount === 0 || undefined}
                    onClick={() => {
                      if (refreshableCount === 0) return;
                      refreshWatched.mutate({});
                    }}
                  >
                    Refresh watched
                  </Button>
                </Tooltip>
              )
            }
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
          <EmptyState
            icon={<IconLibrary size={ICON_SIZE.hero} />}
            title="Your library is empty"
            body="Submit a gallery URL above to start tracking a series. Re-poll watched series on a schedule to keep them current."
            arrow
          />
        )}
        {totalCount > 0 && visible.length === 0 && (
          <EmptyState compact title="No series match the current filters" />
        )}
        {visible.length > 0 && (
          <Stack gap={0}>
            {pagination.pageItems.map((t) => (
              <TargetRow
                key={t.id}
                target={t}
                defaultPeriod={defaultPeriod}
                onOpenJob={onOpenJob}
                expanded={expandedId === t.id}
                onToggle={() => setExpandedId((cur) => (cur === t.id ? null : t.id))}
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
