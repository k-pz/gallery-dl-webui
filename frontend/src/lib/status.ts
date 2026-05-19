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

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "gray";
}

export function isTerminal(status: Status): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function isCancellable(status: Status): boolean {
  return !isTerminal(status);
}
