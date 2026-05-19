import {
  ActionIcon,
  Badge,
  Card,
  Group,
  List,
  Loader,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  cancelDownloadMutation,
  getDownloadQueryKey,
  listDownloadsOptions,
  listDownloadsQueryKey,
  requeueDownloadMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { REFETCH_LIST_MS } from "../lib/polling";
import { CANCELLING_LABEL, isCancellable, isTerminal, statusColor } from "../lib/status";

export function RecentList({
  onSelect,
  selectedId,
}: {
  onSelect: (id: number) => void;
  selectedId: number | null;
}) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    ...listDownloadsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });

  const [cancellingIds, setCancellingIds] = useState<Set<number>>(() => new Set());

  // Prune the optimistic-cancelling set once the row reaches terminal state,
  // so the badge stops lying after the worker has reflected the cancel.
  useEffect(() => {
    if (!data) return;
    setCancellingIds((prev) => {
      if (prev.size === 0) return prev;
      let changed = false;
      const next = new Set(prev);
      for (const id of prev) {
        const item = data.find((d) => d.id === id);
        if (!item || isTerminal(item.status)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [data]);

  const invalidate = (id: number) => {
    queryClient.invalidateQueries({ queryKey: listDownloadsQueryKey() });
    queryClient.invalidateQueries({
      queryKey: getDownloadQueryKey({ path: { download_id: id } }),
    });
  };

  const cancel = useMutation({
    ...cancelDownloadMutation(),
    onMutate: (vars) => {
      const id = vars.path.download_id;
      setCancellingIds((prev) => {
        const next = new Set(prev);
        next.add(id);
        return next;
      });
    },
    onSuccess: (d) => {
      notifications.show({
        title: "Cancel requested",
        message: `Job #${d.id} is being cancelled.`,
        color: "orange",
      });
      invalidate(d.id);
    },
    onError: (err, vars) => {
      const id = vars.path.download_id;
      setCancellingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
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
      const id = vars.path.download_id;
      setCancellingIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    },
    onSuccess: (d) => {
      notifications.show({
        title: "Requeued",
        message: `Job #${d.id} has been queued again.`,
        color: "blue",
      });
      invalidate(d.id);
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

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="xs">
        <Title order={4}>Recent</Title>
        {isLoading && <Loader size="xs" />}
        {data && data.length === 0 && (
          <Text size="sm" c="dimmed">
            No downloads yet.
          </Text>
        )}
        {data && data.length > 0 && (
          <List spacing="xs" listStyleType="none" withPadding={false}>
            {data.map((item) => {
              const inflight = inflightId === item.id;
              const showCancelling = cancellingIds.has(item.id) && !isTerminal(item.status);
              const displayStatus = showCancelling ? CANCELLING_LABEL : item.status;
              const canCancel = isCancellable(item.status) && !showCancelling;
              return (
                <List.Item key={item.id}>
                  <Group gap="sm" wrap="nowrap" align="center">
                    <Group
                      gap="sm"
                      wrap="nowrap"
                      style={{
                        cursor: "pointer",
                        flex: 1,
                        minWidth: 0,
                        fontWeight: item.id === selectedId ? 600 : 400,
                      }}
                      onClick={() => onSelect(item.id)}
                    >
                      <Badge color={statusColor(displayStatus)} variant="light">
                        {displayStatus}
                      </Badge>
                      <Text
                        size="sm"
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          flex: 1,
                        }}
                        title={item.url}
                      >
                        #{item.id} {item.url}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {item.files_downloaded}/{item.files_expected ?? "?"}
                      </Text>
                    </Group>
                    {(canCancel || showCancelling) && (
                      <Tooltip label={showCancelling ? "Cancelling…" : "Cancel"} withArrow>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          loading={(inflight && cancel.isPending) || showCancelling}
                          disabled={inflight || showCancelling}
                          onClick={() => cancel.mutate({ path: { download_id: item.id } })}
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
                          loading={inflight && requeue.isPending}
                          disabled={inflight}
                          onClick={() => requeue.mutate({ path: { download_id: item.id } })}
                          aria-label={`Requeue #${item.id}`}
                        >
                          ↻
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Group>
                </List.Item>
              );
            })}
          </List>
        )}
      </Stack>
    </Card>
  );
}
