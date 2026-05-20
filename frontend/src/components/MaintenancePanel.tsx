import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listMaintenanceJobsOptions,
  listMaintenanceJobsQueryKey,
  scheduleMaintenanceJobMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";

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
        {jobs.data && jobs.data.length > 0 && (
          <Table striped withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ID</Table.Th>
                <Table.Th>Job</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Result</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {jobs.data.map((job) => (
                <Table.Tr key={job.id}>
                  <Table.Td>{job.id}</Table.Td>
                  <Table.Td>{job.kind}</Table.Td>
                  <Table.Td>
                    <Badge>{job.status}</Badge>
                  </Table.Td>
                  <Table.Td>
                    {job.result ? JSON.stringify(job.result) : (job.error ?? "—")}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Card>
  );
}
