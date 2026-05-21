// ETA computation for in-flight jobs.
//
// Strategy: keep a small ring of (timestamp, done) samples per consumer and
// derive the rate from the oldest sample still inside the window. The window
// is sized so a brief stall doesn't immediately wipe the estimate, but the
// rate still trends toward zero if no progress comes through.
//
// When we only have one sample (just opened the panel mid-job), fall back to
// the cumulative rate from `started_at` so the user gets an estimate
// immediately instead of waiting for the next poll.

export interface EtaSample {
  t: number;
  done: number;
}

export const ETA_WINDOW_MS = 60_000;
export const ETA_MAX_SAMPLES = 32;

export type EtaState = { kind: "none" } | { kind: "eta"; remainingMs: number };

export interface EtaInput {
  now: number;
  samples: ReadonlyArray<EtaSample>;
  done: number;
  total: number | null | undefined;
  startedAtMs: number | null | undefined;
}

export function computeEta(input: EtaInput): EtaState {
  const { now, samples, done, total, startedAtMs } = input;
  if (total == null || total <= 0) return { kind: "none" };
  // Nothing done yet → no rate to extrapolate. Caller can show "preparing…".
  if (done <= 0) return { kind: "none" };
  if (done >= total) return { kind: "none" };

  const remaining = total - done;

  let rate: number | null = null;

  if (samples.length > 0) {
    const oldest = samples[0];
    const dt = now - oldest.t;
    const dd = done - oldest.done;
    if (dt > 0 && dd > 0) {
      rate = dd / dt;
    }
  }

  if (rate == null && startedAtMs != null && now > startedAtMs) {
    rate = done / (now - startedAtMs);
  }

  if (rate == null || rate <= 0) return { kind: "none" };

  const remainingMs = remaining / rate;
  if (!Number.isFinite(remainingMs) || remainingMs < 0) return { kind: "none" };

  return { kind: "eta", remainingMs };
}

/**
 * Append a new observation to a sample ring, dropping anything older than
 * `windowMs`. We only push when `done` advanced — repeated identical samples
 * would skew the rolling rate toward zero too eagerly, and an unchanged poll
 * already lets the rate decay naturally (the oldest sample stays put while
 * the wall clock moves forward).
 */
export function recordSample(
  samples: ReadonlyArray<EtaSample>,
  now: number,
  done: number,
  windowMs: number = ETA_WINDOW_MS,
  maxSamples: number = ETA_MAX_SAMPLES,
): EtaSample[] {
  const next = samples.slice();
  const last = next[next.length - 1];
  if (!last || last.done !== done) {
    next.push({ t: now, done });
  }
  while (next.length > 1 && now - next[0].t > windowMs) {
    next.shift();
  }
  while (next.length > maxSamples) {
    next.shift();
  }
  return next;
}

/** Compact human-readable duration. ETAs are approximate so we keep one unit
 * at a time: "45s", "8m", "2h 15m", "3d". */
export function formatEta(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) return `${Math.max(1, totalSec)}s`;
  const totalMin = Math.round(totalSec / 60);
  if (totalMin < 60) return `${totalMin}m`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h < 24) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

export function parseStartedAt(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

export interface DownloadEtaInput {
  files_downloaded: number;
  files_expected?: number | null;
  chapters_total?: number | null;
  postprocess_chapters_packed?: number | null;
}

export interface DownloadEtaDimension {
  done: number;
  total: number | null;
  /** Stable key for the current measurement dimension; used as a resetKey
   * input so the sample ring is rebuilt when the phase flips. */
  phaseKey: "postprocess" | "download" | "unknown";
}

/**
 * Pick the (done, total) pair to track for a download.
 *
 * Postprocess takes priority once it has started (`postprocess_chapters_packed`
 * present) — at that point the download bytes are no longer the bottleneck.
 * Falls back to file counts during the active download, and finally yields
 * `unknown` when the manifest hasn't been resolved yet.
 */
export function downloadEtaDimension(d: DownloadEtaInput): DownloadEtaDimension {
  if (d.postprocess_chapters_packed != null && d.chapters_total != null) {
    return {
      done: d.postprocess_chapters_packed,
      total: d.chapters_total,
      phaseKey: "postprocess",
    };
  }
  if (d.files_expected != null) {
    return { done: d.files_downloaded, total: d.files_expected, phaseKey: "download" };
  }
  return { done: 0, total: null, phaseKey: "unknown" };
}
