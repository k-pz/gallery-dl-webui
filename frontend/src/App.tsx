import {
  Badge,
  Box,
  Button,
  Card,
  Code,
  Container,
  Group,
  List,
  Loader,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  createDownloadMutation,
  getDownloadOptions,
  getHealthOptions,
  listDownloadsOptions,
  listDownloadsQueryKey,
} from "./api/@tanstack/react-query.gen";
import type { DownloadOut } from "./api/types.gen";

type Status = DownloadOut["status"];

const TERMINAL_STATUSES: ReadonlyArray<Status> = ["completed", "failed"];

const STATUS_COLORS: Record<string, string> = {
  pending: "gray",
  running: "blue",
  completed: "green",
  failed: "red",
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "gray";
}

function useDownloadLogs(downloadId: number | null): string[] {
  const [lines, setLines] = useState<string[]>([]);
  useEffect(() => {
    setLines([]);
    if (downloadId === null) {
      return;
    }
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${scheme}//${window.location.host}/api/downloads/${downloadId}/logs`;
    const ws = new WebSocket(url);
    ws.onmessage = (event) => {
      setLines((prev) => [...prev, String(event.data)]);
    };
    return () => {
      ws.close();
    };
  }, [downloadId]);
  return lines;
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
  const logs = useDownloadLogs(jobId);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && logs.length > 0) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs]);

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
        <Box>
          <Text size="xs" c="dimmed" mb={4}>
            live log
          </Text>
          <ScrollArea h={260} viewportRef={scrollRef} type="auto">
            <Code block style={{ fontSize: 12, minHeight: 240, whiteSpace: "pre-wrap" }}>
              {logs.length === 0 ? "(waiting for output…)" : logs.join("\n")}
            </Code>
          </ScrollArea>
        </Box>
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
                    {item.files_downloaded}f
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
