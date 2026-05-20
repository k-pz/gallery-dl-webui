import { ActionIcon, Badge, Card, Group, List, Select, Stack, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  cancelDownloadMutation,
  listDownloadsOptions,
  requeueDownloadMutation,
} from "../api/@tanstack/react-query.gen";
import type { DownloadOut } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { makeNeedleMatcher } from "../lib/listFilters";
import { useOptimisticCancelMany } from "../lib/optimisticCancel";
import { usePagination } from "../lib/pagination";
import { REFETCH_LIST_MS } from "../lib/polling";
import {
  CANCELLING_LABEL,
  isActive,
  isCancellable,
  isTerminal,
  jobStep,
  statusColor,
} from "../lib/status";
import { ListHeader } from "./ListHeader";
import { ListPagination } from "./ListPagination";
import { ListToolbar } from "./ListToolbar";

type StatusFilter = "any" | "active" | "completed" | "failed" | "cancelled";
type SortKey = "recent" | "status";

const STATUS_ORDER: Record<string, number> = {
  pending: 0,
  extracting: 1,
  running: 2,
  completed: 3,
  failed: 4,
  cancelled: 5,
};

function chapterCountLabel(item: DownloadOut): string {
  const total = item.chapters_total;
  if (total == null) return "—";
  const packed = item.postprocess_chapters_packed;
  if (packed != null) return `${packed}/${total} ch.`;
  return `${total} ch.`;
}

export function RecentList({
  onSelect,
  selectedId,
}: {
  onSelect: (id: number) => void;
  selectedId: number | null;
}) {
  const invalidate = useDataInvalidators();
  const { data, isLoading } = useQuery({
    ...listDownloadsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });

  const cancelIntent = useOptimisticCancelMany(data);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("any");
  const [sortKey, setSortKey] = useState<SortKey>("recent");

  const refresh = (id: number) => {
    invalidate.downloads();
    invalidate.download(id);
  };

  const cancel = useMutation({
    ...cancelDownloadMutation(),
    onMutate: (vars) => {
      cancelIntent.mark(vars.path.download_id);
    },
    onSuccess: (d) => {
      notifications.show({
        title: "Cancel requested",
        message: `Job #${d.id} is being cancelled.`,
        color: "orange",
      });
      refresh(d.id);
    },
    onError: (err, vars) => {
      const id = vars.path.download_id;
      cancelIntent.clear(id);
      notifications.show({
        title: `Cancel failed (#${id})`,
        message: extractErrorMessage(err),
        color: "red",
      });
    },
  });

  const requeue = useMutation({
    ...requeueDownloadMutation(),
    onMutate: (vars) => {
      cancelIntent.clear(vars.path.download_id);
    },
    onSuccess: (d) => {
      notifications.show({
        title: "Requeued",
        message: `Job #${d.id} has been queued again.`,
        color: "blue",
      });
      refresh(d.id);
    },
    onError: (err, vars) => {
      notifications.show({
        title: `Requeue failed (#${vars.path.download_id})`,
        message: extractErrorMessage(err),
        color: "red",
      });
    },
  });

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
    if (sortKey === "status") {
      return [...filtered].sort((a, b) => {
        const aOrder = STATUS_ORDER[a.status] ?? 99;
        const bOrder = STATUS_ORDER[b.status] ?? 99;
        if (aOrder !== bOrder) return aOrder - bOrder;
        return b.created_at.localeCompare(a.created_at);
      });
    }
    return filtered;
  }, [data, search, statusFilter, sortKey]);

  const totalCount = data?.length ?? 0;
  const filtersActive = search.trim().length > 0 || statusFilter !== "any";

  const pagination = usePagination(visible, `${search}|${statusFilter}|${sortKey}`);

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="xs">
        <ListHeader
          title="Recent"
          titleOrder={4}
          totalCount={totalCount}
          visibleCount={visible.length}
          filtersActive={filtersActive}
          isLoading={isLoading}
        />
        {totalCount > 0 && (
          <ListToolbar
            search={search}
            setSearch={setSearch}
            searchPlaceholder="Search name or URL"
            searchAriaLabel="Filter downloads by name or URL"
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
            <Select
              label="Sort by"
              data={[
                { value: "recent", label: "Most recent" },
                { value: "status", label: "Status" },
              ]}
              value={sortKey}
              onChange={(v) => setSortKey((v as SortKey) ?? "recent")}
              w={150}
              comboboxProps={{ withinPortal: true }}
            />
          </ListToolbar>
        )}
        {totalCount === 0 && (
          <Text size="sm" c="dimmed">
            No downloads yet.
          </Text>
        )}
        {totalCount > 0 && visible.length === 0 && (
          <Text size="sm" c="dimmed">
            No downloads match the current filters.
          </Text>
        )}
        {visible.length > 0 && (
          <List spacing="xs" listStyleType="none" withPadding={false}>
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
          </List>
        )}
        <ListPagination
          page={pagination.page}
          setPage={pagination.setPage}
          totalPages={pagination.totalPages}
          start={pagination.start}
          end={pagination.end}
          total={pagination.total}
          ariaLabel="Recent jobs pagination"
        />
      </Stack>
    </Card>
  );
}

function RecentRow({
  item,
  selected,
  cancelling,
  inflight,
  isCancelPending,
  isRequeuePending,
  onSelect,
  onCancel,
  onRequeue,
}: {
  item: DownloadOut;
  selected: boolean;
  cancelling: boolean;
  inflight: boolean;
  isCancelPending: boolean;
  isRequeuePending: boolean;
  onSelect: (id: number) => void;
  onCancel: () => void;
  onRequeue: () => void;
}) {
  const showCancelling = cancelling;
  const displayStatus = showCancelling ? CANCELLING_LABEL : item.status;
  const step = jobStep(item.status, item.postprocess_status, showCancelling);
  const canCancel = isCancellable(item.status) && !showCancelling;
  const displayName = item.name ?? item.url;
  const showUrlSubtitle = Boolean(item.name);

  return (
    <List.Item>
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <Stack
          gap={2}
          style={{
            cursor: "pointer",
            flex: 1,
            minWidth: 0,
            fontWeight: selected ? 600 : 400,
          }}
          onClick={() => onSelect(item.id)}
        >
          <Group gap="xs" wrap="nowrap" align="center">
            <Badge color={statusColor(displayStatus)} variant="light">
              {step.label}
            </Badge>
            <Text
              size="sm"
              fw={500}
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                flex: 1,
              }}
              title={displayName}
            >
              #{item.id} {displayName}
            </Text>
            <Text size="xs" c="dimmed">
              {chapterCountLabel(item)}
            </Text>
          </Group>
          {showUrlSubtitle && (
            <Text
              size="xs"
              c="dimmed"
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={item.url}
            >
              {item.url}
            </Text>
          )}
        </Stack>
        {(canCancel || showCancelling) && (
          <Tooltip label={showCancelling ? "Cancelling…" : "Cancel"} withArrow>
            <ActionIcon
              variant="subtle"
              color="red"
              loading={(inflight && isCancelPending) || showCancelling}
              disabled={inflight || showCancelling}
              onClick={onCancel}
              aria-label={`Cancel #${item.id}`}
            >
              ✕
            </ActionIcon>
          </Tooltip>
        )}
        {isTerminal(item.status) && (
          <Tooltip label="Requeue" withArrow>
            <ActionIcon
              variant="subtle"
              loading={inflight && isRequeuePending}
              disabled={inflight}
              onClick={onRequeue}
              aria-label={`Requeue #${item.id}`}
            >
              ↻
            </ActionIcon>
          </Tooltip>
        )}
      </Group>
    </List.Item>
  );
}
