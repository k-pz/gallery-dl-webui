import type { Download } from "../api/types.gen";

export type Status = Download["status"];

// UI-only intermediate label shown after a cancel is requested but before the
// worker has reflected it in the persisted status. Not a backend status.
export const CANCELLING_LABEL = "cancelling";

const STATUS_COLORS: Record<string, string> = {
  pending: "gray",
  extracting: "yellow",
  running: "blue",
  [CANCELLING_LABEL]: "orange",
  completed: "green",
  failed: "red",
  cancelled: "orange",
};

const TERMINAL_STATUSES: ReadonlyArray<Status> = ["completed", "failed", "cancelled"];

const ACTIVE_STATUSES: ReadonlySet<string> = new Set(["pending", "extracting", "running"]);
const RUNNING_STATUSES: ReadonlySet<string> = new Set(["extracting", "running"]);

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "gray";
}

// Maps any job/chapter status string to the canonical `.pill` tone slots so
// every list, badge, and progress strip pulls the same five-tone palette.
export type Tone = "muted" | "active" | "done" | "warn" | "error" | "info";

const STATUS_TONES: Record<string, Tone> = {
  pending: "muted",
  extracting: "warn",
  running: "active",
  downloading: "active",
  downloaded: "info",
  processing: "warn",
  completed: "done",
  failed: "error",
  cancelled: "warn",
  [CANCELLING_LABEL]: "warn",
};

export function statusTone(status: string): Tone {
  return STATUS_TONES[status] ?? "muted";
}

export function isTerminal(status: Status): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function isActive(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function isRunning(status: string): boolean {
  return RUNNING_STATUSES.has(status);
}

export function isScheduled(status: string): boolean {
  return status === "pending";
}

/**
 * Picks the job that should be shown as "currently in focus" in the Jobs
 * tab. Prefers the oldest running job (smallest id, i.e. the one that
 * started first); when nothing is running, falls back to the oldest
 * pending job (next to be processed). Returns null when there are no
 * active jobs at all.
 */
export function pickCurrentActiveJobId(
  downloads: ReadonlyArray<{ id: number; status: string }>,
): number | null {
  let runningId: number | null = null;
  let pendingId: number | null = null;
  for (const d of downloads) {
    if (isRunning(d.status)) {
      if (runningId === null || d.id < runningId) runningId = d.id;
    } else if (isScheduled(d.status)) {
      if (pendingId === null || d.id < pendingId) pendingId = d.id;
    }
  }
  return runningId ?? pendingId;
}

export function isCancellable(status: Status): boolean {
  return !isTerminal(status);
}

const JOB_STATUS_LABELS: Record<string, string> = {
  pending: "Scheduled",
  extracting: "Fetching metadata",
  running: "Downloading",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  [CANCELLING_LABEL]: "Cancelling…",
};

export function jobStatusLabel(status: string): string {
  return JOB_STATUS_LABELS[status] ?? status;
}

const CHAPTER_STAGE_LABELS: Record<string, string> = {
  downloading: "Downloading",
  downloaded: "Downloaded",
  processing: "Processing",
  completed: "Completed",
};

export function chapterStageLabel(stage: string): string {
  return CHAPTER_STAGE_LABELS[stage] ?? stage;
}

// User-facing job lifecycle. We collapse the backend's main run and
// postprocess pass into six stages:
// Scheduled → Fetching metadata → Downloading → Downloaded → Processing → Completed.
export const JOB_STEPS = [
  "Scheduled",
  "Fetching metadata",
  "Downloading",
  "Downloaded",
  "Processing",
  "Completed",
] as const;

export type JobStepName = (typeof JOB_STEPS)[number];

export type JobStepKind = "running" | "done" | "failed" | "cancelled" | "cancelling";

/**
 * Discriminated by `kind`:
 *   - "running":    in-flight; index points at the currently-loading step
 *   - "done":       reached the final step (Completed)
 *   - "failed":     terminal failure
 *   - "cancelled":  terminal cancellation
 *   - "cancelling": cancel requested, job not yet terminal
 *
 * `index` and `total` are always present so the Stepper can position itself.
 */
export type JobStep = {
  index: number;
  label: string;
  total: number;
  kind: JobStepKind;
};

export function jobStep(
  status: string,
  postprocessStatus: string | null | undefined,
  cancelling: boolean = false,
): JobStep {
  const total = JOB_STEPS.length;
  const idx = stepIndexFor(status, postprocessStatus);
  if (cancelling && !isTerminal(status as Status)) {
    return { kind: "cancelling", index: idx, label: "Cancelling…", total };
  }
  if (status === "failed") {
    return { kind: "failed", index: idx, label: "Failed", total };
  }
  if (status === "cancelled") {
    return { kind: "cancelled", index: idx, label: "Cancelled", total };
  }
  const label = JOB_STEPS[Math.min(idx, total - 1)];
  return {
    kind: idx >= total - 1 ? "done" : "running",
    index: idx,
    label,
    total,
  };
}

function stepIndexFor(status: string, postprocessStatus: string | null | undefined): number {
  switch (status) {
    case "pending":
      return 0;
    case "extracting":
      return 1;
    case "running":
      return 2;
    case "completed":
      if (postprocessStatus === null || postprocessStatus === undefined) return 3;
      if (postprocessStatus === "running") return 4;
      // skipped / completed / failed all mean the post-download work is done.
      return 5;
    case "failed":
    case "cancelled":
      // Land on whatever step we were on at the time. We don't track that
      // explicitly, so default to the start — callers should use the
      // failed/cancelled flags for styling, not the index.
      return 0;
    default:
      return 0;
  }
}
