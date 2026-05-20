import {
  ActionIcon,
  Alert,
  Badge,
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
import { usePagination } from "../lib/pagination";
import { ListPagination } from "./ListPagination";
import { MaintenanceLog } from "./MaintenanceLog";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

const STATUS_COLOR: Record<string, string> = {
  pending: "gray",
  running: "blue",
  completed: "green",
  failed: "red",
  cancelled: "orange",
};

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

  return (
    <Stack gap="lg">
      <Card>
        <Stack gap="md">
          <Stack gap={4}>
            <span className="app-section-kicker">background jobs</span>
            <Title order={3}>Schedule maintenance</Title>
            <Text size="sm" c="dimmed">
              One-off jobs that fan out over the library: rename CBZs, refresh series metadata, or
              wipe + re-download from scratch.
            </Text>
          </Stack>
          <Group wrap="wrap">
            <Button
              onClick={() => schedule.mutate({ body: { kind: "rename_chapters" } })}
              loading={schedule.isPending}
            >
              Schedule chapter rename
            </Button>
            <Button
              variant="light"
              onClick={() => schedule.mutate({ body: { kind: "regenerate_series_metadata" } })}
              loading={schedule.isPending}
            >
              Regenerate series metadata
            </Button>
            <Button
              variant="outline"
              color="red"
              onClick={() => {
                const ok = window.confirm(
                  "Rebuild library?\n\n" +
                    "This wipes the download history, the gallery-dl archive, the raw " +
                    "downloads dir, and EVERYTHING under the postprocess root " +
                    "(excluded directory names are spared). The library (your " +
                    "targets) is kept and a fresh download is enqueued for each.",
                );
                if (ok) schedule.mutate({ body: { kind: "rebuild_library" } });
              }}
              loading={schedule.isPending}
            >
              Rebuild library
            </Button>
          </Group>
          {schedule.isError && (
            <Alert color="red" variant="light">
              {extractErrorMessage(schedule.error)}
            </Alert>
          )}
        </Stack>
      </Card>

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
            <Alert color="red" variant="light">
              {extractErrorMessage(jobs.error)}
            </Alert>
          )}
          {cancel.isError && (
            <Alert color="red" variant="light">
              {extractErrorMessage(cancel.error)}
            </Alert>
          )}
          {jobList.length === 0 && !jobs.isLoading && (
            <Box
              style={{
                padding: "1.5rem 1rem",
                textAlign: "center",
                border: "1px dashed var(--app-border-subtle)",
                borderRadius: "var(--mantine-radius-md)",
                background: "var(--app-surface-muted)",
              }}
            >
              <Text size="sm" c="dimmed">
                No maintenance jobs yet.
              </Text>
            </Box>
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
                          <Badge
                            color={STATUS_COLOR[job.status] ?? "gray"}
                            variant="light"
                            size="sm"
                          >
                            {job.status}
                          </Badge>
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
