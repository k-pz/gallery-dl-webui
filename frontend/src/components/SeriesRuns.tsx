import { Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { listDownloadsOptions } from "../api/@tanstack/react-query.gen";
import type { Download } from "../api/types.gen";
import { REFETCH_LIST_MS } from "../lib/polling";
import { jobStatusLabel, statusTone } from "../lib/status";
import { formatAbs, formatRel } from "../lib/time";
import { Pill } from "./Pill";

const MAX_RUNS = 25;

export function runChapters(d: Download): string {
  if (d.chapters_total == null) return "—";
  if (d.postprocess_chapters_packed != null) {
    return `${d.postprocess_chapters_packed}/${d.chapters_total} ch packed`;
  }
  return `${d.chapters_total} ch`;
}

/** The series' downloads, newest first; each opens its job on the Jobs tab. */
export function SeriesRuns({
  targetId,
  onOpenJob,
}: {
  targetId: number;
  onOpenJob: (jobId: number) => void;
}) {
  const { data } = useQuery({ ...listDownloadsOptions(), refetchInterval: REFETCH_LIST_MS });
  const runs = useMemo(
    () =>
      (data ?? [])
        .filter((d) => d.target_id === targetId)
        .sort((a, b) => b.id - a.id)
        .slice(0, MAX_RUNS),
    [data, targetId],
  );
  if (runs.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No downloads yet.
      </Text>
    );
  }
  return (
    <ul className="series-runs">
      {runs.map((d) => (
        <li key={d.id}>
          <button type="button" className="series-run" onClick={() => onOpenJob(d.id)}>
            <span className="series-run-id">#{d.id}</span>
            <span className="series-run-when" title={formatAbs(d.created_at)}>
              {formatRel(d.finished_at ?? d.created_at)}
            </span>
            <span className="series-run-ch">{runChapters(d)}</span>
            <Pill tone={statusTone(d.status)}>{jobStatusLabel(d.status)}</Pill>
          </button>
        </li>
      ))}
    </ul>
  );
}
