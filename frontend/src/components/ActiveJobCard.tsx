import { Badge, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getDownloadOptions } from "../api/@tanstack/react-query.gen";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { isTerminal, statusColor } from "../lib/status";
import { ProgressCard } from "./ProgressCard";

export function ActiveJobCard({ jobId }: { jobId: number }) {
  const { data: job, isLoading } = useQuery({
    ...getDownloadOptions({ path: { download_id: jobId } }),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && isTerminal(status) ? false : REFETCH_ACTIVE_MS;
    },
  });

  if (isLoading || !job) {
    return (
      <Card withBorder shadow="sm" padding="lg">
        <Loader size="sm" />
      </Card>
    );
  }

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>Job #{job.id}</Title>
          <Badge color={statusColor(job.status)}>{job.status}</Badge>
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
        <ProgressCard jobId={jobId} status={job.status} />
      </Stack>
    </Card>
  );
}
