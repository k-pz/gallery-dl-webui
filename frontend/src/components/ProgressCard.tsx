import { Box, Group, Progress, ScrollArea, Stack, Text, Tooltip } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useRef } from "react";
import { getDownloadProgressOptions } from "../api/@tanstack/react-query.gen";
import type { ChapterProgress } from "../api/types.gen";
import { useEta } from "../hooks/useEta";
import { extractErrorMessage } from "../lib/apiError";
import { formatEta } from "../lib/eta";
import { REFETCH_ACTIVE_MS } from "../lib/polling";
import { chapterStageLabel, isTerminal, type Status, statusTone, type Tone } from "../lib/status";
import { Pill } from "./Pill";

type ChapterStage = "downloading" | "downloaded" | "processing" | "completed";

const CHAPTER_LIST_HEIGHT = 220;

function chapterStage(ch: ChapterProgress): ChapterStage {
  if (ch.stage === "downloaded" || ch.stage === "completed" || ch.stage === "processing") {
    return ch.stage;
  }
  return "downloading";
}

// Terminal jobs carry an explicit per-chapter `status` (downloaded/skipped/
// failed); live jobs only carry `stage`. Prefer status for the badge so past
// jobs show what actually happened.
function chapterBadge(ch: ChapterProgress): { label: string; tone: Tone } {
  const key = ch.status ?? ch.stage;
  return { label: chapterStageLabel(key), tone: statusTone(key) };
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
  const { data, isLoading, isError, error } = useQuery({
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

  // Large series carry 1000+ chapters; rendering them all would rebuild the
  // whole list on every progress refetch and freeze the page. Virtualize so
  // only the rows inside the 220px viewport (plus overscan) hit the DOM.
  const viewportRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: totalChapters,
    getScrollElement: () => viewportRef.current,
    estimateSize: () => 48,
    overscan: 10,
    // The first render happens before the viewport is measured; seed the
    // known ScrollArea height so the initial window isn't empty.
    initialRect: { width: 0, height: CHAPTER_LIST_HEIGHT },
  });

  if (isError) {
    return (
      <Stack gap="sm">
        <span className="app-section-kicker">{terminal ? "results" : "progress"}</span>
        <Box className="app-alert">
          <Text size="sm">{extractErrorMessage(error)}</Text>
        </Box>
      </Stack>
    );
  }

  if (isLoading || !data) {
    // Match the laid-out version so the card doesn't visually collapse while
    // we wait for the manifest. Three skeleton rows track the shape of the
    // populated chapter list.
    return (
      <Stack gap="sm" aria-busy="true">
        <Group justify="space-between" align="baseline">
          <span className="app-section-kicker">{terminal ? "results" : "progress"}</span>
          <span className="app-sk" style={{ width: 80, height: 11 }} />
        </Group>
        {!terminal && <span className="app-sk" style={{ width: "100%", height: 8 }} />}
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

  // Chapters have no stable id and two can share a name (e.g. both "(untitled)"),
  // which collides if used directly as a React key. Disambiguate repeats into
  // stable, unique keys instead of falling back to the array index.
  const chapterKeys: string[] = [];
  const seenLabels = new Map<string, number>();
  for (const ch of data.chapters) {
    const label = ch.name || "(untitled)";
    const dup = seenLabels.get(label) ?? 0;
    seenLabels.set(label, dup + 1);
    chapterKeys.push(dup === 0 ? label : `${label}#${dup}`);
  }

  // Finished jobs only report what happened — no transient "fetching…"/ETA
  // labels and no progress bar; the settled chapter tally is the result.
  let rightLabel: string | null;
  if (!manifestReady) rightLabel = terminal ? null : "fetching…";
  else if (packing) rightLabel = `processing… · ${settledChapters} / ${totalChapters} chapters`;
  else if (eta.kind === "eta") {
    rightLabel = `~${formatEta(eta.remainingMs)} · ${settledChapters} / ${totalChapters} chapters`;
  } else rightLabel = `${settledChapters} / ${totalChapters} chapters`;

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="baseline">
        <span className="app-section-kicker">{terminal ? "results" : "progress"}</span>
        {rightLabel && (
          <Text size="sm" c="dimmed" ff="monospace">
            {rightLabel}
          </Text>
        )}
      </Group>
      {!terminal && <Progress value={pct} size="md" radius="sm" striped animated />}
      {(() => {
        const downloaded = data.chapters_downloaded ?? 0;
        const failed = data.chapters_failed ?? 0;
        const skipped = data.chapters_skipped ?? 0;
        if (data.chapters_discovered == null && failed === 0) return null;
        return (
          <Text size="xs" c="dimmed" ff="monospace">
            {[
              data.chapters_discovered != null ? `discovered ${data.chapters_discovered}` : null,
              data.chapters_needed != null ? `needed ${data.chapters_needed}` : null,
              `downloaded ${downloaded}`,
              skipped > 0 ? `skipped ${skipped}` : null,
              `failed ${failed}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </Text>
        );
      })()}
      {terminal && !manifestReady && (
        <Text size="sm" c="dimmed">
          No chapter details were recorded for this run.
        </Text>
      )}
      {manifestReady && (
        <Box
          className="active-job-chapters"
          style={{
            border: "1px solid var(--app-border-subtle)",
            borderRadius: "var(--mantine-radius-md)",
            background: "var(--app-surface-muted)",
          }}
        >
          <ScrollArea h={CHAPTER_LIST_HEIGHT} type="auto" viewportRef={viewportRef}>
            <div
              style={{
                height: virtualizer.getTotalSize(),
                width: "100%",
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((row) => {
                const ch = data.chapters[row.index];
                const badge = chapterBadge(ch);
                const label = ch.name || "(untitled)";
                const meta = [ch.pages ? `${ch.pages}p` : null, ch.date || null]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <div
                    key={chapterKeys[row.index]}
                    data-index={row.index}
                    ref={virtualizer.measureElement}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${row.start}px)`,
                    }}
                  >
                    <Group
                      justify="space-between"
                      gap="xs"
                      wrap="nowrap"
                      py={6}
                      px="xs"
                      style={{
                        borderTop: row.index > 0 ? "1px solid var(--app-border-subtle)" : undefined,
                      }}
                    >
                      <Stack gap={0} style={{ minWidth: 0 }}>
                        <Text
                          size="sm"
                          ff="monospace"
                          style={{
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          title={ch.title || label}
                        >
                          {label}
                        </Text>
                        {meta && (
                          <Text size="xs" c="dimmed" ff="monospace">
                            {meta}
                          </Text>
                        )}
                      </Stack>
                      <Tooltip
                        label={ch.error ?? ""}
                        disabled={!ch.error}
                        withArrow
                        multiline
                        w={260}
                      >
                        <span style={{ display: "inline-flex" }}>
                          <Pill tone={badge.tone}>{badge.label}</Pill>
                        </span>
                      </Tooltip>
                    </Group>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </Box>
      )}
    </Stack>
  );
}
