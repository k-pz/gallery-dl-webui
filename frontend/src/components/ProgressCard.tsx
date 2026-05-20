import { Badge, Box, Group, Loader, Progress, ScrollArea, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getDownloadProgressOptions } from "../api/@tanstack/react-query.gen";
import type { ChapterProgress } from "../api/types.gen";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { chapterStageLabel, isTerminal, type Status } from "../lib/status";

type ChapterStage = "downloading" | "downloaded" | "processing" | "completed";

const STAGE_COLOR: Record<ChapterStage, string> = {
  downloading: "blue",
  downloaded: "cyan",
  processing: "yellow",
  completed: "green",
};

function chapterStage(ch: ChapterProgress): ChapterStage {
  if (ch.stage === "downloaded" || ch.stage === "completed" || ch.stage === "processing") {
    return ch.stage;
  }
  return "downloading";
}

export function ProgressCard({ jobId, status }: { jobId: number; status: Status }) {
  const terminal = isTerminal(status);
  const { data, isLoading } = useQuery({
    ...getDownloadProgressOptions({ path: { download_id: jobId } }),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && isTerminal(s) ? false : REFETCH_ACTIVE_MS;
    },
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

  const totalChapters = data.chapters.length;
  const settledChapters = data.chapters.filter((ch) => chapterStage(ch) !== "downloading").length;
  const pct = totalChapters > 0 ? (settledChapters / totalChapters) * 100 : 0;
  const manifestReady = totalChapters > 0;

  return (
    <Box>
      <Group justify="space-between" mb={4}>
        <Text size="xs" c="dimmed">
          progress
        </Text>
        <Text size="xs" c="dimmed">
          {manifestReady ? `${settledChapters} / ${totalChapters} chapters` : "preparing…"}
        </Text>
      </Group>
      <Progress value={pct} size="md" striped={!terminal} animated={!terminal} />
      {manifestReady && (
        <ScrollArea h={220} mt="sm" type="auto">
          <Stack gap={4}>
            {data.chapters.map((ch) => {
              const stage = chapterStage(ch);
              const label = ch.name || "(root)";
              return (
                <Group key={label} justify="space-between" gap="xs" wrap="nowrap">
                  <Text
                    size="sm"
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={label}
                  >
                    {label}
                  </Text>
                  <Badge size="sm" color={STAGE_COLOR[stage]} variant="light">
                    {chapterStageLabel(stage)}
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
