import { useEffect, useMemo, useState } from "react";
import { isTerminal, type Status } from "./status";

/**
 * Optimistic-cancel flag for a single job view. Returns `cancelling` true
 * between the user clicking Cancel and the backend reflecting it in
 * job.status (at which point the value falls back to false automatically).
 *
 * Consumers call mark() from cancel.onMutate and clear() from requeue.onMutate
 * or cancel.onError; the hook itself resets the flag when jobId changes
 * (focusing a different job) and once status becomes terminal.
 */
export function useOptimisticCancel(
  jobId: number,
  status: string | undefined,
): {
  cancelling: boolean;
  mark: () => void;
  clear: () => void;
} {
  const [flag, setFlag] = useState(false);

  // Reset when the focused job changes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: jobId is the reactive trigger.
  useEffect(() => {
    setFlag(false);
  }, [jobId]);

  // Auto-clear once the underlying job is terminal.
  useEffect(() => {
    if (status && isTerminal(status as Status)) setFlag(false);
  }, [status]);

  const cancelling = flag && !(status && isTerminal(status as Status));
  return {
    cancelling,
    mark: () => setFlag(true),
    clear: () => setFlag(false),
  };
}

/**
 * Optimistic-cancel set for a list of jobs. isCancelling(id) is true only
 * when mark(id) has been called AND the corresponding item is still
 * non-terminal — terminal entries are auto-pruned when `items` updates.
 */
export function useOptimisticCancelMany(items: { id: number; status: string }[] | undefined): {
  isCancelling: (id: number) => boolean;
  mark: (id: number) => void;
  clear: (id: number) => void;
} {
  const [ids, setIds] = useState<Set<number>>(() => new Set());

  useEffect(() => {
    if (!items) return;
    setIds((prev) => {
      if (prev.size === 0) return prev;
      let changed = false;
      const next = new Set(prev);
      for (const id of prev) {
        const item = items.find((d) => d.id === id);
        if (!item || isTerminal(item.status as Status)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [items]);

  const byId = useMemo(() => {
    const m = new Map<number, { id: number; status: string }>();
    if (items) for (const it of items) m.set(it.id, it);
    return m;
  }, [items]);

  return {
    isCancelling: (id: number) => {
      if (!ids.has(id)) return false;
      const item = byId.get(id);
      return !item || !isTerminal(item.status as Status);
    },
    mark: (id: number) =>
      setIds((prev) => {
        if (prev.has(id)) return prev;
        const next = new Set(prev);
        next.add(id);
        return next;
      }),
    clear: (id: number) =>
      setIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      }),
  };
}
