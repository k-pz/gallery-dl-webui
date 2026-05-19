import type { DownloadOut } from "../api/types.gen";

export type Status = DownloadOut["status"];

const STATUS_COLORS: Record<string, string> = {
  pending: "gray",
  extracting: "yellow",
  running: "blue",
  completed: "green",
  failed: "red",
};

const TERMINAL_STATUSES: ReadonlyArray<Status> = ["completed", "failed"];

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "gray";
}

export function isTerminal(status: Status): boolean {
  return TERMINAL_STATUSES.includes(status);
}
