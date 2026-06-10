import {
  Box,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  cancelMaintenanceJobMutation,
  listMaintenanceJobsOptions,
  listMaintenanceJobsQueryKey,
  scheduleMaintenanceJobMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { KIND_LABEL, maintStatusLabel, TERMINAL_STATUSES } from "../lib/maintenance";
import { usePagination } from "../lib/pagination";
import { statusTone } from "../lib/status";
import { EmptyState } from "./EmptyState";
import {
  IconAlertTriangle,
  IconChevronDown,
  IconClock,
  IconEyeOff,
  IconFileText,
  IconRefresh,
  IconX,
} from "./Icons";
import { ListPagination } from "./ListPagination";
import { MaintenanceLog } from "./MaintenanceLog";
import { Pill } from "./Pill";
import { PushKomgaStatusCard } from "./PushKomgaStatusCard";
import { RebuildLibraryCard } from "./RebuildLibraryCard";
import { UpdateLxcCard } from "./UpdateLxcCard";

export function MaintenancePanel() {
  const qc = useQueryClient();
  const jobs = useQuery({
    ...listMaintenanceJobsOptions(),
    refetchInterval: 3000,
  });
  const schedule = useMutation({
    ...scheduleMaintenanceJobMutation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: listMaintenanceJobsQueryKey() }),
  });
  const cancel = useMutation({
    ...cancelMaintenanceJobMutation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: listMaintenanceJobsQueryKey() }),
  });

  const jobList = jobs.data ?? [];
  const pagination = usePagination(jobList, "maintenance");
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  const [userPicked, setUserPicked] = useState(false);
  useEffect(() => {
    if (userPicked) return;
    if (jobList.length === 0) {
      setSelectedJobId(null);
      return;
    }
    setSelectedJobId(jobList[0].id);
  }, [jobList, userPicked]);

  const scheduleError = schedule.isError ? extractErrorMessage(schedule.error) : null;
  // One shared mutation backs six unrelated buttons; gate each button's
  // spinner on the kind it actually submits so clicking one doesn't put
  // the whole tab into a loading state.
  const schedulingKind = schedule.isPending ? schedule.variables?.body?.kind : undefined;

  return (
    <Stack gap="lg">
      <Card>
        <Stack gap="md">
          <Stack gap={4}>
            <span className="app-section-kicker">postprocessing</span>
            <Title order={3}>Schedule maintenance</Title>
            <Text size="sm" c="dimmed">
              One-off jobs that sweep the whole library: rename CBZs, refresh series metadata. Safe
              to run repeatedly (idempotent) — re-running won't double up or undo earlier runs.
            </Text>
          </Stack>
          <Group wrap="wrap">
            <Button
              variant="light"
              leftSection={<IconRefresh size={14} />}
              onClick={() => schedule.mutate({ body: { kind: "rename_chapters" } })}
              loading={schedulingKind === "rename_chapters"}
            >
              Schedule chapter rename
            </Button>
            <Button
              variant="light"
              leftSection={<IconFileText size={14} />}
              onClick={() => schedule.mutate({ body: { kind: "regenerate_series_metadata" } })}
              loading={schedulingKind === "regenerate_series_metadata"}
            >
              Regenerate series metadata
            </Button>
            <Button
              variant="light"
              leftSection={<IconEyeOff size={14} />}
              onClick={() => schedule.mutate({ body: { kind: "unwatch_ended_series" } })}
              loading={schedulingKind === "unwatch_ended_series"}
            >
              Unwatch ended series
            </Button>
          </Group>
          {scheduleError && (
            <Box className="app-alert">
              <Text size="sm">{scheduleError}</Text>
            </Box>
          )}
        </Stack>
      </Card>

      <PushKomgaStatusCard
        scheduling={schedulingKind === "push_komga_series_status"}
        onSchedule={() => schedule.mutate({ body: { kind: "push_komga_series_status" } })}
      />

      <UpdateLxcCard
        scheduling={schedulingKind === "update_lxc"}
        onSchedule={() => schedule.mutateAsync({ body: { kind: "update_lxc" } })}
      />

      <RebuildLibraryCard
        scheduling={schedulingKind === "rebuild_library"}
        onSchedule={() => schedule.mutate({ body: { kind: "rebuild_library" } })}
      />

      <Card>
        <Stack gap="md">
          <Stack gap={4}>
            <span className="app-section-kicker">history</span>
            <Group justify="space-between" align="baseline">
              <Title order={4}>Maintenance jobs</Title>
              {jobs.isLoading && <Loader size="xs" />}
            </Group>
          </Stack>
          {jobs.isError && (
            <Box className="app-alert">
              <IconAlertTriangle size={16} className="alert-icon" />
              <Text size="sm">{extractErrorMessage(jobs.error)}</Text>
            </Box>
          )}
          {cancel.isError && (
            <Box className="app-alert">
              <IconAlertTriangle size={16} className="alert-icon" />
              <Text size="sm">{extractErrorMessage(cancel.error)}</Text>
            </Box>
          )}
          {jobList.length === 0 && !jobs.isLoading && (
            <EmptyState
              icon={<IconClock size={20} />}
              title="No maintenance jobs yet"
              body="Jobs you schedule above — and what they did — show up here."
            />
          )}
          {jobList.length > 0 && (
            <Box
              style={{
                border: "1px solid var(--app-border-subtle)",
                borderRadius: "var(--mantine-radius-md)",
                overflow: "hidden",
              }}
            >
              <Table
                verticalSpacing="sm"
                highlightOnHover
                stickyHeader
                className="maint-jobs-table"
              >
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th style={{ width: 64 }}>ID</Table.Th>
                    <Table.Th>Job</Table.Th>
                    <Table.Th style={{ width: 140 }}>Status</Table.Th>
                    <Table.Th>Result</Table.Th>
                    <Table.Th style={{ width: 56 }} aria-label="Actions" />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {pagination.pageItems.map((job) => {
                    const cancellable = !TERMINAL_STATUSES.has(job.status);
                    const isSelected = selectedJobId === job.id;
                    const isCancelling =
                      cancel.isPending && cancel.variables?.path?.job_id === job.id;
                    return (
                      <Table.Tr
                        key={job.id}
                        onClick={() => {
                          setSelectedJobId(job.id);
                          setUserPicked(true);
                        }}
                        style={{
                          cursor: "pointer",
                          backgroundColor: isSelected ? "var(--app-surface-muted)" : undefined,
                        }}
                        aria-label={`Select maintenance job ${job.id}`}
                      >
                        <Table.Td>
                          <Text size="sm" ff="monospace" c="dimmed">
                            {job.id}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={2}>
                            <Text size="sm" fw={500}>
                              {KIND_LABEL[job.kind] ?? job.kind}
                            </Text>
                            <Text size="xs" c="dimmed" ff="monospace">
                              {job.kind}
                            </Text>
                          </Stack>
                        </Table.Td>
                        <Table.Td>
                          <Pill tone={statusTone(job.status)}>{maintStatusLabel(job.status)}</Pill>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={4}>
                            {job.kind === "push_komga_series_status" && (
                              <KomgaMatchWarnings result={job.result} />
                            )}
                            <MaintResultCell
                              text={job.result ? JSON.stringify(job.result) : (job.error ?? "—")}
                              empty={!job.result && !job.error}
                              jobId={job.id}
                            />
                          </Stack>
                        </Table.Td>
                        <Table.Td>
                          {cancellable && (
                            <Tooltip label="Cancel job" withArrow>
                              <button
                                type="button"
                                className="icon-btn"
                                data-tone="danger"
                                aria-label={`Cancel maintenance job ${job.id}`}
                                // aria-disabled (not native `disabled`) keeps the
                                // button hoverable so the Tooltip still fires while
                                // the cancel is in flight; the click is guarded below.
                                aria-disabled={isCancelling ? "true" : undefined}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (isCancelling) return;
                                  cancel.mutate({ path: { job_id: job.id } });
                                }}
                              >
                                {isCancelling ? (
                                  <Loader size={16} color="red" />
                                ) : (
                                  <IconX size={16} />
                                )}
                              </button>
                            </Tooltip>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Box>
          )}
          <ListPagination
            page={pagination.page}
            setPage={pagination.setPage}
            totalPages={pagination.totalPages}
            start={pagination.start}
            end={pagination.end}
            total={pagination.total}
            ariaLabel="Maintenance jobs pagination"
          />
          {selectedJobId !== null && jobList.length > 0 && (
            <>
              <Divider />
              <MaintenanceLog
                jobId={selectedJobId}
                startedAt={jobList.find((j) => j.id === selectedJobId)?.started_at}
              />
            </>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

/** Names the series a Komga push couldn't sync, so the user knows what to fix.
 *
 * The push job's result carries `unmatched` (no Komga series with that name)
 * and `ambiguous` (several exact matches) alongside the counters; rendering
 * them here saves digging through the raw JSON or the job log.
 */
function KomgaMatchWarnings({ result }: { result: { [key: string]: unknown } | null }) {
  const unmatched = stringList(result?.unmatched);
  const ambiguous = stringList(result?.ambiguous);
  if (unmatched.length === 0 && ambiguous.length === 0) return null;
  return (
    <Stack gap={2}>
      {unmatched.length > 0 && (
        <Text size="xs" c="orange">
          No Komga match ({unmatched.length}): {unmatched.join(", ")}
        </Text>
      )}
      {ambiguous.length > 0 && (
        <Text size="xs" c="orange">
          Ambiguous Komga match ({ambiguous.length}): {ambiguous.join(", ")}
        </Text>
      )}
    </Stack>
  );
}

function MaintResultCell({ text, empty, jobId }: { text: string; empty: boolean; jobId: number }) {
  const [expanded, setExpanded] = useState(false);

  // No payload and no error: nothing to expand, just the placeholder.
  if (empty) {
    return (
      <Text size="xs" ff="monospace" c="dimmed">
        {text}
      </Text>
    );
  }

  return (
    <Stack gap={4} className="maint-result-wrap">
      {expanded ? (
        <Text
          size="xs"
          ff="monospace"
          c="dimmed"
          className="maint-result maint-result-full"
          data-testid={`maint-result-full-${jobId}`}
        >
          {text}
        </Text>
      ) : (
        <Text size="xs" ff="monospace" c="dimmed" className="maint-result">
          {text}
        </Text>
      )}
      <UnstyledButton
        className="maint-result-toggle"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
        aria-expanded={expanded}
        aria-label={
          expanded
            ? `Collapse result for maintenance job ${jobId}`
            : `Expand result for maintenance job ${jobId}`
        }
        data-expanded={expanded ? "true" : undefined}
      >
        <Text size="xs" c="dimmed" ff="monospace">
          {expanded ? "collapse" : "expand"}
        </Text>
        <IconChevronDown size={14} className="maint-result-toggle-chev" />
      </UnstyledButton>
    </Stack>
  );
}
