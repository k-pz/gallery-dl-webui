/**
 * Client-side mirror of the backend's duration parser
 * (backend/src/backend/targets/utils.py): compact specs like `30s`, `5m`,
 * `2h`, `1d`, `1w`, combinable (`1d12h`), whitespace tolerated, bare
 * numbers rejected. Keep the two in sync.
 */

const DURATION_FULL = /^\s*(?:\d+\s*[smhdw]\s*)+$/i;
const DURATION_PART = /(\d+)\s*[smhdw]/gi;

export function isValidDuration(raw: string): boolean {
  if (!raw || !DURATION_FULL.test(raw)) return false;
  let total = 0;
  for (const m of raw.matchAll(DURATION_PART)) total += Number(m[1]);
  return total > 0;
}

export const DURATION_FORMAT_HINT = "Use formats like 30m, 2h, 1d or 1d12h.";
