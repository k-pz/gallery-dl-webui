import {
  ActionIcon,
  Box,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  cancelMaintenanceJobMutation,
  listMaintenanceJobsOptions,
  listMaintenanceJobsQueryKey,
  scheduleMaintenanceJobMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { usePagination } from "../lib/pagination";
import { statusTone } from "../lib/status";
import { EmptyState } from "./EmptyState";
import { IconAlertTriangle, IconClock, IconFileText, IconRefresh } from "./Icons";
import { ListPagination } from "./ListPagination";
import { MaintenanceLog } from "./MaintenanceLog";
import { Pill } from "./Pill";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

// The literal the user must type to arm the rebuild. Kept short, lowercase
// only — anything longer becomes annoying to type for a deliberately
// frequent-enough op.
const REBUILD_CONFIRM_WORD = "rebuild";

const KIND_LABEL: Record<string, string> = {
  rename_chapters: "Rename chapters",
  regenerate_series_metadata: "Regenerate series metadata",
  rebuild_library: "Rebuild library",
};

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

  return (
    <Stack gap="lg">
      <Card>
        <Stack gap="md">
          <Stack gap={4}>
            <span className="app-section-kicker">postprocessing</span>
            <Title order={3}>Schedule maintenance</Title>
            <Text size="sm" c="dimmed">
              One-off jobs that fan out over the library: rename CBZs, refresh series metadata. Safe
              and idempotent.
            </Text>
          </Stack>
          <Group wrap="wrap">
            <Button
              variant="light"
              leftSection={<IconRefresh size={14} />}
              onClick={() => schedule.mutate({ body: { kind: "rename_chapters" } })}
              loading={schedule.isPending}
            >
              Schedule chapter rename
            </Button>
            <Button
              variant="light"
              leftSection={<IconFileText size={14} />}
              onClick={() => schedule.mutate({ body: { kind: "regenerate_series_metadata" } })}
              loading={schedule.isPending}
            >
              Regenerate series metadata
            </Button>
          </Group>
          {scheduleError && (
            <Box className="app-alert">
              <Text size="sm">{scheduleError}</Text>
            </Box>
          )}
        </Stack>
      </Card>

      <RebuildLibraryCard
        scheduling={schedule.isPending}
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
              body="Scheduled background jobs (rename, regenerate, rebuild) and their results show up here."
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
              <Table verticalSpacing="sm" highlightOnHover stickyHeader>
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
                          <Pill tone={statusTone(job.status)}>{job.status}</Pill>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs" ff="monospace" c="dimmed" lineClamp={1}>
                            {job.result ? JSON.stringify(job.result) : (job.error ?? "—")}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          {cancellable && (
                            <Tooltip label="Cancel job" withArrow>
                              <ActionIcon
                                variant="subtle"
                                color="red"
                                aria-label={`Cancel maintenance job ${job.id}`}
                                loading={
                                  cancel.isPending && cancel.variables?.path?.job_id === job.id
                                }
                                onClick={(e) => {
                                  e.stopPropagation();
                                  cancel.mutate({ path: { job_id: job.id } });
                                }}
                              >
                                ✕
                              </ActionIcon>
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
              <MaintenanceLog jobId={selectedJobId} />
            </>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}

/**
 * Destructive op lives on its own card with a red border and a type-to-confirm
 * field. The button doesn't accept the click until the user has typed exactly
 * `rebuild`, so a stray cursor never wipes anyone's library.
 */
function RebuildLibraryCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const [typed, setTyped] = useState("");
  const matches = useMemo(() => typed.trim().toLowerCase() === REBUILD_CONFIRM_WORD, [typed]);

  const reset = () => {
    setArmed(false);
    setTyped("");
  };

  return (
    <Card className="maintenance-destructive">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
            <span className="app-section-kicker">destructive</span>
            <Title order={3} style={{ color: "var(--tone-error)" }}>
              Rebuild library
            </Title>
            <Text size="sm" c="dimmed">
              Wipes every downloaded chapter, the gallery-dl archive, the raw downloads dir, and
              everything under the postprocess root (excluded directory names are spared). Every
              watched series is re-queued from scratch. There's no undo. Plan to be offline for
              several hours.
            </Text>
          </Stack>
          <IconAlertTriangle size={20} style={{ color: "var(--tone-error)", flexShrink: 0 }} />
        </Group>
        {!armed ? (
          <Group>
            <Button
              variant="outline"
              color="red"
              leftSection={<IconAlertTriangle size={14} />}
              onClick={() => setArmed(true)}
              loading={scheduling}
            >
              Rebuild library…
            </Button>
          </Group>
        ) : (
          <Stack gap="sm">
            <Text size="sm">
              To confirm, type <span className="code-chip">{REBUILD_CONFIRM_WORD}</span> below. The
              next run is scheduled immediately and cannot be reverted.
            </Text>
            <Group gap="sm" wrap="wrap" align="flex-end">
              <TextInput
                aria-label="Type rebuild to confirm"
                placeholder={REBUILD_CONFIRM_WORD}
                value={typed}
                onChange={(e) => setTyped(e.currentTarget.value)}
                style={{ flex: 1, minWidth: 200, maxWidth: 240 }}
                styles={{ input: { fontFamily: "var(--app-mono)" } }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && matches) {
                    onSchedule();
                    reset();
                  }
                }}
                autoFocus
              />
              <Button
                color="red"
                leftSection={<IconAlertTriangle size={14} />}
                disabled={!matches}
                loading={scheduling}
                onClick={() => {
                  onSchedule();
                  reset();
                }}
              >
                Rebuild library
              </Button>
              <Button variant="subtle" color="gray" onClick={reset} disabled={scheduling}>
                Cancel
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
