import { Box, Group, Progress, ScrollArea, Stack, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { getDownloadProgressOptions } from "../api/@tanstack/react-query.gen";
import type { ChapterProgress } from "../api/types.gen";
import { useEta } from "../hooks/useEta";
import { formatEta } from "../lib/eta";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { chapterStageLabel, isTerminal, type Status, statusTone } from "../lib/status";
import { Pill } from "./Pill";

type ChapterStage = "downloading" | "downloaded" | "processing" | "completed";

function chapterStage(ch: ChapterProgress): ChapterStage {
  if (ch.stage === "downloaded" || ch.stage === "completed" || ch.stage === "processing") {
    return ch.stage;
  }
  return "downloading";
}

export function ProgressCard({
  jobId,
  status,
  startedAt,
}: {
  jobId: number;
  status: Status;
  startedAt: string | null | undefined;
}) {
  const terminal = isTerminal(status);
  const { data, isLoading } = useQuery({
    ...getDownloadProgressOptions({ path: { download_id: jobId } }),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && isTerminal(s) ? false : REFETCH_ACTIVE_MS;
    },
  });

  const totalChapters = data?.chapters.length ?? 0;
  const settledChapters =
    data?.chapters.filter((ch) => chapterStage(ch) !== "downloading").length ?? 0;
  const manifestReady = totalChapters > 0;
  // While packing, the download bar is full but the job hasn't fully wrapped.
  // We pause the ETA — the chapter-level bar is saturated, so any rolling
  // rate would just be noise.
  const packing = manifestReady && !terminal && settledChapters >= totalChapters;

  const eta = useEta({
    resetKey: `prog:${jobId}`,
    startedAt,
    done: settledChapters,
    total: manifestReady ? totalChapters : null,
    active: manifestReady && !terminal && !packing,
  });

  if (isLoading || !data) {
    // Match the laid-out version so the card doesn't visually collapse while
    // we wait for the manifest. Three skeleton rows track the shape of the
    // populated chapter list.
    return (
      <Stack gap="sm" aria-busy="true">
        <Group justify="space-between" align="baseline">
          <span className="app-section-kicker">progress</span>
          <span className="app-sk" style={{ width: 80, height: 11 }} />
        </Group>
        <span className="app-sk" style={{ width: "100%", height: 8 }} />
        <Box
          style={{
            border: "1px solid var(--app-border-subtle)",
            borderRadius: "var(--mantine-radius-md)",
            background: "var(--app-surface-muted)",
            padding: 8,
          }}
        >
          <Stack gap={8}>
            {[0, 1, 2].map((i) => (
              <Group key={i} justify="space-between">
                <span className="app-sk" style={{ width: 120, height: 14 }} />
                <span className="app-sk" style={{ width: 64, height: 14, borderRadius: 999 }} />
              </Group>
            ))}
          </Stack>
        </Box>
      </Stack>
    );
  }

  const pct = totalChapters > 0 ? (settledChapters / totalChapters) * 100 : 0;

  let rightLabel: string;
  if (!manifestReady) rightLabel = "preparing…";
  else if (packing) rightLabel = `packing… · ${settledChapters} / ${totalChapters}`;
  else if (eta.kind === "eta") {
    rightLabel = `~${formatEta(eta.remainingMs)} · ${settledChapters} / ${totalChapters} chapters`;
  } else rightLabel = `${settledChapters} / ${totalChapters} chapters`;

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="baseline">
        <span className="app-section-kicker">progress</span>
        <Text size="sm" c="dimmed" ff="monospace">
          {rightLabel}
        </Text>
      </Group>
      <Progress value={pct} size="md" radius="sm" striped={!terminal} animated={!terminal} />
      {manifestReady && (
        <Box
          className="active-job-chapters"
          style={{
            border: "1px solid var(--app-border-subtle)",
            borderRadius: "var(--mantine-radius-md)",
            background: "var(--app-surface-muted)",
          }}
        >
          <ScrollArea h={220} type="auto">
            <Stack gap={0} p="xs">
              {data.chapters.map((ch, i) => {
                const stage = chapterStage(ch);
                const label = ch.name || "(root)";
                return (
                  <Group
                    key={label}
                    justify="space-between"
                    gap="xs"
                    wrap="nowrap"
                    py={6}
                    px="xs"
                    style={{
                      borderTop: i > 0 ? "1px solid var(--app-border-subtle)" : undefined,
                    }}
                  >
                    <Text
                      size="sm"
                      ff="monospace"
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={label}
                    >
                      {label}
                    </Text>
                    <Pill tone={statusTone(stage)}>{chapterStageLabel(stage)}</Pill>
                  </Group>
                );
              })}
            </Stack>
          </ScrollArea>
        </Box>
      )}
    </Stack>
  );
}
