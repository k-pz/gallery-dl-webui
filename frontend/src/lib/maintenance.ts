export const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

export const KIND_LABEL: Record<string, string> = {
  rename_chapters: "Rename chapters",
  regenerate_series_metadata: "Regenerate series metadata",
  rebuild_library: "Rebuild library",
  push_komga_series_status: "Push series status to Komga",
  update_lxc: "Update LXC from upstream",
  unwatch_ended_series: "Unwatch ended series",
};
