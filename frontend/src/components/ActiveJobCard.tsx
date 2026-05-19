import { Badge, Button, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  cancelDownloadMutation,
  getDownloadOptions,
  getDownloadQueryKey,
  listDownloadsQueryKey,
  requeueDownloadMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { CANCELLING_LABEL, isCancellable, isTerminal, statusColor } from "../lib/status";
import { ProgressCard } from "./ProgressCard";

export function ActiveJobCard({ jobId }: { jobId: number }) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [cancelIntent, setCancelIntent] = useState(false);

  const { data: job, isLoading } = useQuery({
    ...getDownloadOptions({ path: { download_id: jobId } }),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && isTerminal(status) ? false : REFETCH_ACTIVE_MS;
    },
  });

  // Clear the optimistic "cancelling" flag once the backend has reflected a
  // terminal status — covers both successful cancels and races where the job
  // completed or failed before the worker saw the cancel request.
  useEffect(() => {
    if (job && isTerminal(job.status)) setCancelIntent(false);
  }, [job]);

  // Reset the flag whenever the focused job changes; otherwise the badge for
  // a freshly-selected job could briefly show "cancelling" from a prior one.
  // biome-ignore lint/correctness/useExhaustiveDependencies: jobId is the reactive trigger; body intentionally uses no other deps.
  useEffect(() => {
    setCancelIntent(false);
    setActionError(null);
  }, [jobId]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: listDownloadsQueryKey() });
    queryClient.invalidateQueries({
      queryKey: getDownloadQueryKey({ path: { download_id: jobId } }),
    });
  };

  const cancel = useMutation({
    ...cancelDownloadMutation(),
    onMutate: () => {
      setCancelIntent(true);
    },
    onSuccess: () => {
      setActionError(null);
      notifications.show({
        title: "Cancel requested",
        message: `Job #${jobId} is being cancelled.`,
        color: "orange",
      });
      invalidate();
    },
    onError: (err) => {
      setCancelIntent(false);
      const msg = extractErrorMessage(err);
      setActionError(msg);
      notifications.show({
        title: "Cancel failed",
        message: msg,
        color: "red",
      });
    },
  });

  const requeue = useMutation({
    ...requeueDownloadMutation(),
    onMutate: () => {
      setCancelIntent(false);
    },
    onSuccess: () => {
      setActionError(null);
      notifications.show({
        title: "Requeued",
        message: `Job #${jobId} has been queued again.`,
        color: "blue",
      });
      invalidate();
    },
    onError: (err) => {
      const msg = extractErrorMessage(err);
      setActionError(msg);
      notifications.show({
        title: "Requeue failed",
        message: msg,
        color: "red",
      });
    },
  });

  if (isLoading || !job) {
    return (
      <Card withBorder shadow="sm" padding="lg">
        <Loader size="sm" />
      </Card>
    );
  }

  const showCancelling = cancelIntent && !isTerminal(job.status);
  const displayStatus = showCancelling ? CANCELLING_LABEL : job.status;
  const canCancel = isCancellable(job.status) && !showCancelling;
  const canRequeue = isTerminal(job.status);
  const busy = cancel.isPending || requeue.isPending;

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>Job #{job.id}</Title>
          <Group gap="xs">
            <Badge color={statusColor(displayStatus)}>{displayStatus}</Badge>
            {(canCancel || showCancelling) && (
              <Button
                size="xs"
                variant="light"
                color="red"
                loading={cancel.isPending || showCancelling}
                disabled={busy || showCancelling}
                onClick={() => cancel.mutate({ path: { download_id: job.id } })}
              >
                Cancel
              </Button>
            )}
            {canRequeue && (
              <Button
                size="xs"
                variant="light"
                loading={requeue.isPending}
                disabled={busy}
                onClick={() => requeue.mutate({ path: { download_id: job.id } })}
              >
                Requeue
              </Button>
            )}
          </Group>
        </Group>
        <Text size="sm" style={{ wordBreak: "break-all" }}>
          {job.url}
        </Text>
        <Group gap="lg">
          <Text size="sm">
            <Text span c="dimmed">
              extractor:{" "}
            </Text>
            {job.extractor ?? "—"}
          </Text>
          <Text size="sm">
            <Text span c="dimmed">
              files:{" "}
            </Text>
            {job.files_downloaded}
            {job.files_expected !== null && ` / ${job.files_expected}`}
          </Text>
          {job.exit_code !== null && (
            <Text size="sm">
              <Text span c="dimmed">
                exit:{" "}
              </Text>
              {job.exit_code}
            </Text>
          )}
        </Group>
        {job.error && (
          <Text size="sm" c="red">
            {job.error}
          </Text>
        )}
        {actionError && (
          <Text size="sm" c="red">
            {actionError}
          </Text>
        )}
        <ProgressCard jobId={jobId} status={job.status} />
      </Stack>
    </Card>
  );
}
