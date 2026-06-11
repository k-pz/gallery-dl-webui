import {
  Anchor,
  Box,
  Button,
  Card,
  Divider,
  Group,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getDownloadOptions } from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useCancelDownload, useRequeueDownload } from "../lib/downloadActions";
import { formatEta } from "../lib/eta";
import { useOptimisticCancel } from "../lib/optimisticCancel";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { isCancellable, isTerminal, jobStep } from "../lib/status";
import { formatAbs } from "../lib/time";
import { CopyIconButton } from "./CopyIconButton";
import { IconAlertTriangle, IconX } from "./Icons";
import { JobDetailField } from "./JobDetailField";
import { JobStepper } from "./JobStepper";
import { ProgressCard } from "./ProgressCard";

export function ActiveJobCard({ jobId, onClose }: { jobId: number; onClose?: () => void }) {
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: job,
    isLoading,
    isError,
    error,
  } = useQuery({
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

  const cancel = useCancelDownload({
    markCancelling: () => cancelIntent.mark(),
    clearCancelling: () => cancelIntent.clear(),
    onSuccess: () => setActionError(null),
    onError: (err) => setActionError(extractErrorMessage(err)),
  });

  const requeue = useRequeueDownload({
    clearCancelling: () => cancelIntent.clear(),
    onSuccess: () => setActionError(null),
    onError: (err) => setActionError(extractErrorMessage(err)),
  });

  if (isError) {
    // A persistent failure (job pruned server-side, backend down) must not
    // render as an eternal skeleton.
    return (
      <Card>
        <Box className="app-alert">
          <IconAlertTriangle size={16} className="alert-icon" />
          <Text size="sm">{extractErrorMessage(error)}</Text>
        </Box>
      </Card>
    );
  }

  if (isLoading || !job) {
    return (
      <Card>
        <Stack gap="lg">
          <Stack gap={4}>
            <Group gap="sm">
              <span className="app-section-kicker">job</span>
              <span className="app-sk" style={{ width: 30, height: 11 }} />
            </Group>
            <span className="app-sk" style={{ width: "70%", height: 24 }} />
            <span className="app-sk" style={{ width: "40%", height: 12 }} />
          </Stack>
          <Group gap={6} wrap="nowrap">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Group key={i} gap={6} wrap="nowrap" style={{ flex: i < 5 ? 1 : undefined }}>
                <span className="app-sk" style={{ width: 22, height: 22, borderRadius: 999 }} />
                {i < 5 && (
                  <div
                    style={{
                      flex: 1,
                      height: 1,
                      background: "var(--app-border-subtle)",
                    }}
                  />
                )}
              </Group>
            ))}
          </Group>
          <Divider />
          <Group gap="xl">
            <Stack gap={4}>
              <span className="app-sk" style={{ width: 50, height: 9 }} />
              <span className="app-sk" style={{ width: 80, height: 14 }} />
            </Stack>
          </Group>
          <Stack gap="xs">
            <span className="app-sk" style={{ width: 80, height: 9 }} />
            <span className="app-sk" style={{ width: "100%", height: 8 }} />
          </Stack>
        </Stack>
      </Card>
    );
  }

  const showCancelling = cancelIntent.cancelling;
  const step = jobStep(job.status, job.postprocess_status, showCancelling);
  const terminal = isTerminal(job.status);
  const canCancel = isCancellable(job.status) && !showCancelling;
  const canRequeue = terminal;
  const busy = cancel.isPending || requeue.isPending;
  const displayName = job.name ?? job.url;
  const showUrlSubtitle = Boolean(job.name);
  const duration =
    job.started_at && job.finished_at
      ? formatEta(Date.parse(job.finished_at) - Date.parse(job.started_at))
      : null;

  return (
    <Card>
      <Stack gap="lg">
        <Stack gap={4}>
          <Group justify="space-between" align="center" wrap="nowrap">
            <Group gap="sm" wrap="wrap" align="center">
              <span className="app-section-kicker">{terminal ? "job" : "active job"}</span>
              <Text size="xs" c="dimmed" ff="monospace">
                #{job.id}
              </Text>
            </Group>
            {onClose && (
              <Tooltip label="Close job details" withArrow>
                <button
                  type="button"
                  className="icon-btn"
                  data-size="sm"
                  aria-label="Close job details"
                  onClick={onClose}
                >
                  <IconX size={14} />
                </button>
              </Tooltip>
            )}
          </Group>
          <Group
            className="active-job-head"
            justify="space-between"
            align="flex-start"
            wrap="nowrap"
          >
            <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
              <Title order={3} style={{ wordBreak: "break-word" }}>
                {displayName}
              </Title>
              <Group gap={4} wrap="nowrap" align="center">
                {showUrlSubtitle && (
                  <Anchor href={job.url} target="_blank" rel="noreferrer" className="app-url">
                    {job.url}
                  </Anchor>
                )}
                <CopyIconButton value={job.url} label="Copy URL" />
              </Group>
            </Stack>
            <Group className="active-job-head-actions" gap="xs">
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
          <JobDetailField label="Extractor" value={job.extractor ?? "—"} mono />
          <JobDetailField label="Started" value={formatAbs(job.started_at)} mono />
          {job.finished_at && (
            <JobDetailField label="Finished" value={formatAbs(job.finished_at)} mono />
          )}
          {duration && <JobDetailField label="Duration" value={duration} mono />}
        </Group>
        {job.error && (
          <Box className="app-alert">
            <IconAlertTriangle size={16} className="alert-icon" />
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" fw={600}>
                Job error
              </Text>
              <Text size="sm">{job.error}</Text>
            </Box>
            <CopyIconButton value={job.error} label="Copy error message" />
          </Box>
        )}
        {actionError && (
          <Box className="app-alert">
            <IconAlertTriangle size={16} className="alert-icon" />
            <Text size="sm">{actionError}</Text>
          </Box>
        )}
        <ProgressCard jobId={jobId} status={job.status} startedAt={job.started_at} />
      </Stack>
    </Card>
  );
}
