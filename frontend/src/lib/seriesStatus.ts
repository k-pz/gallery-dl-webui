import type { PillTone } from "../components/Pill";

// Komga-compatible publication-status labels. Keep this list in sync with
// `SERIES_STATUSES` in backend/src/backend/downloads/postprocess.py.
export const SERIES_STATUS_OPTIONS = [
  { value: "Ongoing", label: "Ongoing" },
  { value: "Ended", label: "Ended" },
  { value: "Hiatus", label: "Hiatus" },
  { value: "Abandoned", label: "Abandoned" },
] as const;

export const SERIES_STATUS_VALUES = SERIES_STATUS_OPTIONS.map((o) => o.value);

// Series that are done publishing — a refresh would never find new chapters.
// Keep in sync with REFRESH_EXCLUDED_SERIES_STATUSES in
// backend/src/backend/targets/service.py.
export const FINISHED_SERIES_STATUSES: ReadonlyArray<string> = ["Ended", "Abandoned"];

export type SeriesStatus = (typeof SERIES_STATUS_OPTIONS)[number]["value"];

const TONES: Record<SeriesStatus, PillTone> = {
  Ongoing: "active",
  Ended: "done",
  Hiatus: "warn",
  Abandoned: "error",
};

export function seriesStatusTone(status: string | null | undefined): PillTone | undefined {
  if (!status) return undefined;
  return TONES[status as SeriesStatus] ?? "muted";
}
