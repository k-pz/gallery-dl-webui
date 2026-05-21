import { useRef } from "react";
import {
  computeEta,
  type EtaSample,
  type EtaState,
  parseStartedAt,
  recordSample,
} from "../lib/eta";

export interface UseEtaArgs {
  /**
   * Stable identity for the (job, phase) being measured. Sample history is
   * scrapped whenever this changes — e.g. a download flipping from the
   * download phase to the postprocess phase needs a fresh rate, since the
   * units of `done`/`total` change.
   */
  resetKey: string;
  startedAt: string | null | undefined;
  done: number;
  total: number | null | undefined;
  /** False once the job is terminal — the hook freezes its last samples. */
  active: boolean;
}

interface RingState {
  key: string;
  samples: EtaSample[];
}

/**
 * Tracks rolling samples for a single job/phase and returns the current ETA.
 *
 * Sampling happens lazily during render: each render with new args appends
 * (when `done` advanced) and prunes anything beyond the rolling window. We
 * intentionally avoid useEffect/useState here — the samples are pure derived
 * state from the polled query data and don't need to drive re-renders on
 * their own.
 */
export function useEta(args: UseEtaArgs): EtaState {
  const { resetKey, startedAt, done, total, active } = args;
  const ring = useRef<RingState>({ key: resetKey, samples: [] });

  if (ring.current.key !== resetKey) {
    ring.current = { key: resetKey, samples: [] };
  }

  if (!active) {
    return { kind: "none" };
  }

  const now = Date.now();
  // `done` going backwards (cancel→requeue, manifest reshape) would poison
  // the rolling rate. Drop the ring and start over.
  const last = ring.current.samples[ring.current.samples.length - 1];
  if (last && done < last.done) {
    ring.current.samples = [];
  }

  ring.current.samples = recordSample(ring.current.samples, now, done);

  return computeEta({
    now,
    samples: ring.current.samples,
    done,
    total,
    startedAtMs: parseStartedAt(startedAt),
  });
}
