import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Stepper,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  cancelDownloadMutation,
  getDownloadOptions,
  requeueDownloadMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { isCancellable, isTerminal, JOB_STEPS, jobStep, statusColor } from "../lib/status";
import { ProgressCard } from "./ProgressCard";

export function ActiveJobCard({ jobId }: { jobId: number }) {
  const invalidate = useDataInvalidators();
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

  const refresh = () => {
    invalidate.downloads();
    invalidate.download(jobId);
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
      refresh();
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
      refresh();
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
  const step = jobStep(job.status, job.postprocess_status, showCancelling);
  const canCancel = isCancellable(job.status) && !showCancelling;
  const canRequeue = isTerminal(job.status);
  const busy = cancel.isPending || requeue.isPending;
  const displayName = job.name ?? job.url;
  const showUrlSubtitle = Boolean(job.name);

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Title order={4} style={{ wordBreak: "break-word" }}>
              {displayName}
            </Title>
            {showUrlSubtitle && (
              <Anchor
                href={job.url}
                target="_blank"
                rel="noreferrer"
                size="xs"
                c="dimmed"
                style={{ wordBreak: "break-all" }}
              >
                {job.url}
              </Anchor>
            )}
            <Text size="xs" c="dimmed">
              Job #{job.id}
            </Text>
          </Stack>
          <Group gap="xs">
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
        <JobStepper job={{ status: job.status, step }} />
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

function JobStepper({ job }: { job: { status: string; step: ReturnType<typeof jobStep> } }) {
  const { step } = job;
  if (step.kind === "failed" || step.kind === "cancelled") {
    return (
      <Group gap="xs">
        <Badge size="lg" color={statusColor(job.status)} variant="filled">
          {step.label}
        </Badge>
      </Group>
    );
  }
  // Stepper's `active` is the next-incomplete index. For a done job we pass
  // total so every step renders as complete.
  const active = step.kind === "done" ? step.total : step.index;
  return (
    <Stepper
      active={active}
      size="xs"
      iconSize={20}
      color={step.kind === "cancelling" ? "orange" : undefined}
    >
      {JOB_STEPS.map((label, i) => (
        <Stepper.Step
          key={label}
          label={label}
          loading={step.kind === "running" && i === step.index}
        />
      ))}
    </Stepper>
  );
}
