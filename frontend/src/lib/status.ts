import type { DownloadOut } from "../api/types.gen";

export type Status = DownloadOut["status"];

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

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "gray";
}

export function isTerminal(status: Status): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function isActive(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function isCancellable(status: Status): boolean {
  return !isTerminal(status);
}

// User-facing job lifecycle. We collapse the backend's three-stage main run
// (pending → extracting → running) plus the separate postprocess pass into a
// five-step picture: Scheduled → Fetching metadata → Downloading → Processing
// → Completed.
export const JOB_STEPS = [
  "Scheduled",
  "Fetching metadata",
  "Downloading",
  "Processing",
  "Completed",
] as const;

export type JobStepName = (typeof JOB_STEPS)[number];

export type JobStep = {
  /** 0-based index into JOB_STEPS for the currently-active step. */
  index: number;
  label: string;
  total: number;
  /** True when the job's terminal status is failed/cancelled — Stepper styling. */
  failed: boolean;
  cancelled: boolean;
  cancelling: boolean;
  /** True when every step is done (Completed). */
  done: boolean;
};

export function jobStep(
  status: string,
  postprocessStatus: string | null | undefined,
  cancelling: boolean = false,
): JobStep {
  const total = JOB_STEPS.length;
  if (cancelling && !isTerminal(status as Status)) {
    return {
      index: stepIndexFor(status, postprocessStatus),
      label: "Cancelling…",
      total,
      failed: false,
      cancelled: false,
      cancelling: true,
      done: false,
    };
  }
  if (status === "failed") {
    return {
      index: stepIndexFor(status, postprocessStatus),
      label: "Failed",
      total,
      failed: true,
      cancelled: false,
      cancelling: false,
      done: false,
    };
  }
  if (status === "cancelled") {
    return {
      index: stepIndexFor(status, postprocessStatus),
      label: "Cancelled",
      total,
      failed: false,
      cancelled: true,
      cancelling: false,
      done: false,
    };
  }
  const idx = stepIndexFor(status, postprocessStatus);
  return {
    index: idx,
    label: JOB_STEPS[Math.min(idx, total - 1)],
    total,
    failed: false,
    cancelled: false,
    cancelling: false,
    done: idx >= total - 1,
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
      if (postprocessStatus === "running") return 3;
      // skipped / completed / failed / null all mean the post-download work is done.
      return 4;
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
