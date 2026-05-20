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
import { useMutation, useQuery } from "@tanstack/react-query";
import { extractErrorMessage } from "../lib/apiError";

type MaintenanceJob = {
  id: number;
  kind: string;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
};

async function listJobs(): Promise<MaintenanceJob[]> {
  const res = await fetch("/api/maintenance/jobs");
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as MaintenanceJob[];
}

async function scheduleRenameJob(): Promise<MaintenanceJob> {
  const res = await fetch("/api/maintenance/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "rename_chapters" }),
  });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as MaintenanceJob;
}

export function MaintenancePanel() {
  const jobs = useQuery({
    queryKey: ["maintenance-jobs"],
    queryFn: listJobs,
    refetchInterval: 3000,
  });
  const schedule = useMutation({
    mutationFn: scheduleRenameJob,
    onSuccess: async () => {
      await jobs.refetch();
    },
  });

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="md">
        <Title order={3}>Maintenance</Title>
        <Text size="sm" c="dimmed">
          Schedule background maintenance jobs.
        </Text>
        <Group>
          <Button onClick={() => schedule.mutate()} loading={schedule.isPending}>
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
