import { Card, Group, Select, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  cancelDownloadMutation,
  listDownloadsOptions,
  requeueDownloadMutation,
} from "../api/@tanstack/react-query.gen";
import type { DownloadOut } from "../api/types.gen";
import { useDataInvalidators } from "../lib/invalidate";
import { makeNeedleMatcher } from "../lib/listFilters";
import { useOptimisticCancelMany } from "../lib/optimisticCancel";
import { usePagination } from "../lib/pagination";
import { REFETCH_LIST_MS } from "../lib/polling";
import { isActive } from "../lib/status";
import { useNotifyingMutation } from "../lib/useNotifyingMutation";
import { EmptyState } from "./EmptyState";
import { IconActivity } from "./Icons";
import { ListHeader } from "./ListHeader";
import { ListPagination } from "./ListPagination";
import { ListToolbar } from "./ListToolbar";
import { RecentRow } from "./RecentRow";
import { type SortDir, SortDirToggle } from "./SortDirToggle";

type StatusFilter = "any" | "active" | "completed" | "failed" | "cancelled";
type SortKey = "queue" | "recent" | "status";

const STATUS_ORDER: Record<string, number> = {
  pending: 0,
  extracting: 1,
  running: 2,
  completed: 3,
  failed: 4,
  cancelled: 5,
};

// Queue-order ranking: in-flight first (running, extracting), then pending
// in FIFO order (smallest id = next to be processed). Terminal jobs trail
// behind by recency. Used for the default sort on the Jobs tab.
const QUEUE_RANK: Record<string, number> = {
  running: 0,
  extracting: 1,
  pending: 2,
  completed: 3,
  cancelled: 3,
  failed: 3,
};

export function RecentList({
  onSelect,
  selectedId,
  hideEmpty,
}: {
  onSelect: (id: number) => void;
  selectedId: number | null;
  hideEmpty?: boolean;
}) {
  const invalidate = useDataInvalidators();
  const { data, isLoading } = useQuery({
    ...listDownloadsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });

  const cancelIntent = useOptimisticCancelMany(data);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [sortKey, setSortKey] = useState<SortKey>("queue");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const refresh = (id: number) => {
    invalidate.downloads();
    invalidate.download(id);
  };

  const cancel = useNotifyingMutation(
    {
      ...cancelDownloadMutation(),
      onMutate: (vars) => {
        cancelIntent.mark(vars.path.download_id);
      },
      onSuccess: (d) => refresh(d.id),
      onError: (_err, vars) => cancelIntent.clear(vars.path.download_id),
    },
    {
      success: {
        title: "Cancel requested",
        message: (d) => `Job #${d.id} is being cancelled.`,
        color: "orange",
      },
      error: { title: (_err, vars) => `Cancel failed (#${vars.path.download_id})` },
    },
  );

  const requeue = useNotifyingMutation(
    {
      ...requeueDownloadMutation(),
      onMutate: (vars) => {
        cancelIntent.clear(vars.path.download_id);
      },
      onSuccess: (d) => refresh(d.id),
    },
    {
      success: {
        title: "Requeued",
        message: (d) => `Job #${d.id} has been queued again.`,
        color: "blue",
      },
      error: { title: (_err, vars) => `Requeue failed (#${vars.path.download_id})` },
    },
  );

  const inflightId =
    cancel.isPending && cancel.variables
      ? cancel.variables.path.download_id
      : requeue.isPending && requeue.variables
        ? requeue.variables.path.download_id
        : null;

  const visible = useMemo(() => {
    if (!data) return [];
    const matchesNeedle = makeNeedleMatcher<DownloadOut>(
      search,
      (d) => d.name,
      (d) => d.url,
    );
    const filtered = data.filter((d) => {
      if (!matchesNeedle(d)) return false;
      if (statusFilter !== "any") {
        if (statusFilter === "active" && !isActive(d.status)) return false;
        if (statusFilter === "completed" && d.status !== "completed") return false;
        if (statusFilter === "failed" && d.status !== "failed") return false;
        if (statusFilter === "cancelled" && d.status !== "cancelled") return false;
      }
      return true;
    });
    const dir = sortDir === "asc" ? 1 : -1;
    if (sortKey === "status") {
      return [...filtered].sort((a, b) => {
        const aOrder = STATUS_ORDER[a.status] ?? 99;
        const bOrder = STATUS_ORDER[b.status] ?? 99;
        if (aOrder !== bOrder) return dir * (aOrder - bOrder);
        return b.created_at.localeCompare(a.created_at);
      });
    }
    if (sortKey === "queue") {
      return [...filtered].sort((a, b) => {
        const aRank = QUEUE_RANK[a.status] ?? 99;
        const bRank = QUEUE_RANK[b.status] ?? 99;
        if (aRank !== bRank) return dir * (aRank - bRank);
        // Within active ranks (running/extracting/pending), smaller id = next.
        // Within terminal, larger id = more recent.
        if (aRank < 3) return dir * (a.id - b.id);
        return dir * (b.id - a.id);
      });
    }
    return [...filtered].sort((a, b) => dir * a.created_at.localeCompare(b.created_at));
  }, [data, search, statusFilter, sortKey, sortDir]);

  const totalCount = data?.length ?? 0;
  const filtersActive = search.trim().length > 0 || statusFilter !== "active";

  const pagination = usePagination(visible, `${search}|${statusFilter}|${sortKey}|${sortDir}`);

  const kicker =
    statusFilter === "active" ? "queue" : statusFilter === "any" ? "all jobs" : "history";

  return (
    <Card>
      <Stack gap="md">
        <Stack gap={4}>
          <span className="app-section-kicker">{kicker}</span>
          <ListHeader
            title="Jobs"
            titleOrder={4}
            totalCount={totalCount}
            visibleCount={visible.length}
            filtersActive={filtersActive}
            isLoading={isLoading}
          />
        </Stack>
        {totalCount > 0 && (
          <ListToolbar
            search={search}
            setSearch={setSearch}
            searchPlaceholder="Search name or URL"
            searchAriaLabel="Filter jobs by name or URL"
            searchMinWidth={180}
          >
            <Select
              label="Status"
              data={[
                { value: "any", label: "Any" },
                { value: "active", label: "Active" },
                { value: "completed", label: "Completed" },
                { value: "failed", label: "Failed" },
                { value: "cancelled", label: "Cancelled" },
              ]}
              value={statusFilter}
              onChange={(v) => setStatusFilter((v as StatusFilter) ?? "any")}
              w={140}
              comboboxProps={{ withinPortal: true }}
            />
            <Group gap={4} align="flex-end" wrap="nowrap">
              <Select
                label="Sort by"
                data={[
                  { value: "queue", label: "Queue order" },
                  { value: "recent", label: "Most recent" },
                  { value: "status", label: "Status" },
                ]}
                value={sortKey}
                onChange={(v) => setSortKey((v as SortKey) ?? "queue")}
                w={150}
                comboboxProps={{ withinPortal: true }}
              />
              <SortDirToggle dir={sortDir} sortKey={sortKey} onToggle={setSortDir} />
            </Group>
          </ListToolbar>
        )}
        {totalCount === 0 && !hideEmpty && (
          <EmptyState
            icon={<IconActivity size={22} />}
            title="No jobs yet"
            body="When you submit a URL the queue lands here. Watched series schedule jobs automatically."
          />
        )}
        {totalCount > 0 && visible.length === 0 && (
          <Text size="sm" c="dimmed">
            No jobs match the current filters.
          </Text>
        )}
        {visible.length > 0 && (
          <Stack gap={2}>
            {pagination.pageItems.map((item) => (
              <RecentRow
                key={item.id}
                item={item}
                selected={item.id === selectedId}
                cancelling={cancelIntent.isCancelling(item.id)}
                inflight={inflightId === item.id}
                isCancelPending={cancel.isPending}
                isRequeuePending={requeue.isPending}
                onSelect={onSelect}
                onCancel={() => cancel.mutate({ path: { download_id: item.id } })}
                onRequeue={() => requeue.mutate({ path: { download_id: item.id } })}
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
          ariaLabel="Jobs pagination"
        />
      </Stack>
    </Card>
  );
}
