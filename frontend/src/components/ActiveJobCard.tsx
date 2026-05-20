import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Divider,
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
import { useOptimisticCancel } from "../lib/optimisticCancel";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { isCancellable, isTerminal, JOB_STEPS, jobStep, statusColor } from "../lib/status";
import { ProgressCard } from "./ProgressCard";

export function ActiveJobCard({ jobId }: { jobId: number }) {
  const invalidate = useDataInvalidators();
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: job, isLoading } = useQuery({
    ...getDownloadOptions({ path: { download_id: jobId } }),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && isTerminal(status) ? false : REFETCH_ACTIVE_MS;
    },
  });

  const cancelIntent = useOptimisticCancel(jobId, job?.status);

  // biome-ignore lint/correctness/useExhaustiveDependencies: jobId is the reactive trigger.
  useEffect(() => {
    setActionError(null);
  }, [jobId]);

  const refresh = () => {
    invalidate.downloads();
    invalidate.download(jobId);
  };

  const cancel = useMutation({
    ...cancelDownloadMutation(),
    onMutate: () => {
      cancelIntent.mark();
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
      cancelIntent.clear();
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
      cancelIntent.clear();
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
      <Card>
        <Group>
          <Loader size="sm" />
          <Text c="dimmed" size="sm">
            Loading job…
          </Text>
        </Group>
      </Card>
    );
  }

  const showCancelling = cancelIntent.cancelling;
  const step = jobStep(job.status, job.postprocess_status, showCancelling);
  const canCancel = isCancellable(job.status) && !showCancelling;
  const canRequeue = isTerminal(job.status);
  const busy = cancel.isPending || requeue.isPending;
  const displayName = job.name ?? job.url;
  const showUrlSubtitle = Boolean(job.name);

  return (
    <Card>
      <Stack gap="lg">
        <Stack gap={4}>
          <Group gap="sm" wrap="wrap" align="center">
            <span className="app-section-kicker">active job</span>
            <Text size="xs" c="dimmed" ff="monospace">
              #{job.id}
            </Text>
          </Group>
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
              <Title order={3} style={{ wordBreak: "break-word" }}>
                {displayName}
              </Title>
              {showUrlSubtitle && (
                <Anchor href={job.url} target="_blank" rel="noreferrer" className="app-url">
                  {job.url}
                </Anchor>
              )}
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
        </Stack>
        <JobStepper job={{ status: job.status, step }} />
        <Divider />
        <Group gap="xl" wrap="wrap">
          <DetailField label="Extractor" value={job.extractor ?? "—"} mono />
          {job.exit_code !== null && (
            <DetailField label="Exit code" value={String(job.exit_code)} mono />
          )}
        </Group>
        {job.error && (
          <Alert color="red" variant="light" title="Job error">
            {job.error}
          </Alert>
        )}
        {actionError && (
          <Alert color="red" variant="light">
            {actionError}
          </Alert>
        )}
        <ProgressCard jobId={jobId} status={job.status} />
      </Stack>
    </Card>
  );
}

function DetailField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" style={{ letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {label}
      </Text>
      <Text size="sm" ff={mono ? "monospace" : undefined}>
        {value}
      </Text>
    </Stack>
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
