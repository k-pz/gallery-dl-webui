import {
  Badge,
  Box,
  Button,
  Card,
  Container,
  Group,
  List,
  Loader,
  Progress,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  createDownloadMutation,
  getDownloadOptions,
  getDownloadProgressOptions,
  getHealthOptions,
  listDownloadsOptions,
  listDownloadsQueryKey,
} from "./api/@tanstack/react-query.gen";
import type { DownloadOut } from "./api/types.gen";

type Status = DownloadOut["status"];

const TERMINAL_STATUSES: ReadonlyArray<Status> = ["completed", "failed"];

const STATUS_COLORS: Record<string, string> = {
  pending: "gray",
  extracting: "yellow",
  running: "blue",
  completed: "green",
  failed: "red",
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "gray";
}

function SubmitForm({ onCreated }: { onCreated: (id: number) => void }) {
  const [url, setUrl] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    ...createDownloadMutation(),
    onSuccess: (data) => {
      setUrl("");
      setSubmitError(null);
      onCreated(data.id);
      queryClient.invalidateQueries({ queryKey: listDownloadsQueryKey() });
    },
    onError: (err) => {
      const detail = (err as { detail?: unknown } | null | undefined)?.detail;
      const message =
        typeof detail === "string" ? detail : err instanceof Error ? err.message : "request failed";
      setSubmitError(message);
    },
  });

  const submit = () => {
    const trimmed = url.trim();
    if (!trimmed) {
      setSubmitError("url is required");
      return;
    }
    mutation.mutate({ body: { url: trimmed } });
  };

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Title order={3}>New download</Title>
        <Group align="flex-end" gap="sm" wrap="nowrap">
          <TextInput
            style={{ flex: 1 }}
            label="Gallery URL"
            placeholder="https://mangadex.org/title/..."
            value={url}
            onChange={(e) => setUrl(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                submit();
              }
            }}
            disabled={mutation.isPending}
          />
          <Button onClick={submit} loading={mutation.isPending}>
            Download
          </Button>
        </Group>
        {submitError && (
          <Text size="sm" c="red">
            {submitError}
          </Text>
        )}
      </Stack>
    </Card>
  );
}

function ProgressCard({ jobId, status }: { jobId: number; status: Status }) {
  const isTerminal = TERMINAL_STATUSES.includes(status);
  const { data, isLoading } = useQuery({
    ...getDownloadProgressOptions({ path: { download_id: jobId } }),
    refetchInterval: isTerminal ? false : 1000,
  });

  if (isLoading || !data) {
    return (
      <Box>
        <Text size="xs" c="dimmed" mb={4}>
          progress
        </Text>
        <Loader size="sm" />
      </Box>
    );
  }

  const expected = data.files_expected ?? 0;
  const present = data.files_present;
  const pct = expected > 0 ? (present / expected) * 100 : 0;
  const manifestReady = expected > 0 && data.chapters.length > 0;

  return (
    <Box>
      <Group justify="space-between" mb={4}>
        <Text size="xs" c="dimmed">
          progress
        </Text>
        <Text size="xs" c="dimmed">
          {manifestReady ? `${present} / ${expected} files` : "preparing…"}
        </Text>
      </Group>
      <Progress value={pct} size="md" striped={!isTerminal} animated={!isTerminal} />
      {manifestReady && (
        <ScrollArea h={220} mt="sm" type="auto">
          <Stack gap={4}>
            {data.chapters.map((ch) => {
              const done = ch.files_present === ch.files_total;
              return (
                <Group key={ch.name || "(root)"} justify="space-between" gap="xs" wrap="nowrap">
                  <Text
                    size="sm"
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={ch.name || "(root)"}
                  >
                    {ch.name || "(root)"}
                  </Text>
                  <Badge size="sm" color={done ? "green" : "blue"} variant="light">
                    {ch.files_present}/{ch.files_total}
                  </Badge>
                </Group>
              );
            })}
          </Stack>
        </ScrollArea>
      )}
    </Box>
  );
}

function ActiveJobCard({ jobId }: { jobId: number }) {
  const { data: job, isLoading } = useQuery({
    ...getDownloadOptions({ path: { download_id: jobId } }),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (status && TERMINAL_STATUSES.includes(status)) {
        return false;
      }
      return 1000;
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

function RecentList({
  onSelect,
  selectedId,
}: {
  onSelect: (id: number) => void;
  selectedId: number | null;
}) {
  const { data, isLoading } = useQuery({
    ...listDownloadsOptions(),
    refetchInterval: 2000,
  });

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="xs">
        <Title order={4}>Recent</Title>
        {isLoading && <Loader size="xs" />}
        {data && data.length === 0 && (
          <Text size="sm" c="dimmed">
            No downloads yet.
          </Text>
        )}
        {data && data.length > 0 && (
          <List spacing="xs" listStyleType="none" withPadding={false}>
            {data.map((item) => (
              <List.Item key={item.id}>
                <Group
                  gap="sm"
                  wrap="nowrap"
                  style={{
                    cursor: "pointer",
                    fontWeight: item.id === selectedId ? 600 : 400,
                  }}
                  onClick={() => onSelect(item.id)}
                >
                  <Badge color={statusColor(item.status)} variant="light">
                    {item.status}
                  </Badge>
                  <Text
                    size="sm"
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      flex: 1,
                    }}
                    title={item.url}
                  >
                    #{item.id} {item.url}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {item.files_downloaded}/{item.files_expected ?? "?"}
                  </Text>
                </Group>
              </List.Item>
            ))}
          </List>
        )}
      </Stack>
    </Card>
  );
}

function HealthBadge() {
  const { data, isLoading, error } = useQuery(getHealthOptions());
  return (
    <Group gap="xs">
      <Text size="xs" c="dimmed">
        backend
      </Text>
      {isLoading && <Loader size="xs" />}
      {data && <Badge color="green">{data.status}</Badge>}
      {error && <Badge color="red">unreachable</Badge>}
    </Group>
  );
}

function App() {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  return (
    <Container size="md" py="xl">
      <Stack gap="md">
        <Group justify="space-between" align="flex-end">
          <Title order={1}>gallery-dl-webui</Title>
          <HealthBadge />
        </Group>
        <SubmitForm onCreated={setSelectedId} />
        {selectedId !== null && <ActiveJobCard jobId={selectedId} />}
        <RecentList onSelect={setSelectedId} selectedId={selectedId} />
      </Stack>
    </Container>
  );
}

export default App;
