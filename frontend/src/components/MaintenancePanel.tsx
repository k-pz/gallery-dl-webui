import {
  ActionIcon,
  Alert,
  Badge,
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

  // Auto-follow whatever the freshest job is until the user picks a specific
  // row to inspect. Once they click a row, we stop overriding their choice.
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
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="md">
        <Title order={3}>Maintenance</Title>
        <Text size="sm" c="dimmed">
          Schedule background maintenance jobs.
        </Text>
        <Group>
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
        </Group>
        {schedule.isError && (
          <Alert color="red" variant="light">
            {extractErrorMessage(schedule.error)}
          </Alert>
        )}
        {jobs.isLoading && (
          <Group>
            <Loader size="sm" />
            <Text>Loading maintenance jobs…</Text>
          </Group>
        )}
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
        {jobList.length > 0 && (
          <Table striped withTableBorder highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ID</Table.Th>
                <Table.Th>Job</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Result</Table.Th>
                <Table.Th aria-label="Actions" />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pagination.pageItems.map((job) => {
                const cancellable = !TERMINAL_STATUSES.has(job.status);
                return (
                  <Table.Tr
                    key={job.id}
                    onClick={() => {
                      setSelectedJobId(job.id);
                      setUserPicked(true);
                    }}
                    style={{
                      cursor: "pointer",
                      backgroundColor:
                        selectedJobId === job.id ? "var(--mantine-color-default-hover)" : undefined,
                    }}
                    aria-label={`Select maintenance job ${job.id}`}
                  >
                    <Table.Td>{job.id}</Table.Td>
                    <Table.Td>{job.kind}</Table.Td>
                    <Table.Td>
                      <Badge>{job.status}</Badge>
                    </Table.Td>
                    <Table.Td>
                      {job.result ? JSON.stringify(job.result) : (job.error ?? "—")}
                    </Table.Td>
                    <Table.Td>
                      {cancellable && (
                        <Tooltip label="Cancel job" withArrow>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            aria-label={`Cancel maintenance job ${job.id}`}
                            loading={cancel.isPending && cancel.variables?.path?.job_id === job.id}
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
        {selectedJobId !== null && (
          <>
            <Divider />
            <MaintenanceLog jobId={selectedJobId} />
          </>
        )}
      </Stack>
    </Card>
  );
}
