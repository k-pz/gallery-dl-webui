export const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

export const KIND_LABEL: Record<string, string> = {
  rename_chapters: "Rename chapters",
  regenerate_series_metadata: "Regenerate series metadata",
  refresh_series_metadata: "Refresh series metadata",
  rebuild_library: "Rebuild library",
  push_komga_series_status: "Push series status to Komga",
  sync_komga_metadata: "Sync series metadata to Komga",
  update_lxc: "Update LXC from upstream",
  unwatch_ended_series: "Unwatch ended series",
};

// Maintenance jobs share the download lifecycle vocabulary but not its
// meaning: a maintenance job that is `running` is not "Downloading", and a
// `pending` one is "Queued", not "Scheduled". So we route through a small
// maint-specific map instead of jobStatusLabel().
const MAINT_STATUS_LABELS: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function maintStatusLabel(status: string): string {
  return MAINT_STATUS_LABELS[status] ?? status;
}
