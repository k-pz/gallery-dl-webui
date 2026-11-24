import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { listDownloadsOptions } from "../api/@tanstack/react-query.gen";
import type { Download, Target } from "../api/types.gen";
import { displayName } from "../lib/library";
import { REFETCH_LIST_MS } from "../lib/polling";
import { isRunning, isScheduled, isTerminal, jobStatusLabel, statusTone } from "../lib/status";
import { formatRel } from "../lib/time";
import { Pill } from "./Pill";
import { runChapters } from "./SeriesRuns";

const RECENT_LIMIT = 15;

/**
 * Library-wide activity beside the packer on very wide screens: what is
 * downloading, what is queued and what finished last, so a poll or an add
 * can be followed without leaving the library. Each entry opens its job.
 */
export function ActivityRail({
  targets,
  onOpenJob,
}: {
  targets: ReadonlyArray<Target>;
  onOpenJob: (jobId: number) => void;
}) {
  const { data } = useQuery({ ...listDownloadsOptions(), refetchInterval: REFETCH_LIST_MS });
  const names = useMemo(() => new Map(targets.map((t) => [t.id, displayName(t)])), [targets]);
  const { running, queued, recent } = useMemo(() => {
    const list = data ?? [];
    return {
      running: list.filter((d) => isRunning(d.status)),
      queued: list.filter((d) => isScheduled(d.status)),
      recent: list
        .filter((d) => isTerminal(d.status))
        .sort((a, b) => (b.finished_at ?? "").localeCompare(a.finished_at ?? ""))
        .slice(0, RECENT_LIMIT),
    };
  }, [data]);
  const nameOf = (d: Download) => (d.target_id != null ? names.get(d.target_id) : null) ?? d.url;

  const section = (title: string, items: Download[], empty: string) => (
    <div className="rail-section">
      <h3 className="rail-title">
        {title} <span className="rail-count">{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="rail-empty">{empty}</p>
      ) : (
        <ul className="rail-list">
          {items.map((d) => (
            <li key={d.id}>
              <button type="button" className="rail-item" onClick={() => onOpenJob(d.id)}>
                <span className="rail-item-name">{nameOf(d)}</span>
                <span className="rail-item-meta">
                  #{d.id} · {runChapters(d)}
                  {d.finished_at ? ` · ${formatRel(d.finished_at)}` : ""}
                </span>
                <Pill tone={statusTone(d.status)}>{jobStatusLabel(d.status)}</Pill>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <aside className="lib-pane lib-rail" aria-label="Activity">
      <div className="lib-pane-title">
        <span className="app-section-kicker">Activity</span>
      </div>
      <div className="lib-pane-scroll lib-rail-body">
        {section("Running", running, "Nothing downloading.")}
        {section("Queued", queued, "Queue is empty.")}
        {section("Finished", recent, "No finished jobs yet.")}
      </div>
    </aside>
  );
}
