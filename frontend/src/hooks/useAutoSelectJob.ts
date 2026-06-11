/**
 * Auto-open the "current" job (running, falling back to pending) so the Jobs
 * tab shows what's happening by default, and advance to the next active job
 * when the one we opened finishes. Only selections this hook made itself are
 * acted on — manual picks and explicit closes are respected.
 */

import { useEffect, useRef, useState } from "react";
import { isTerminal, pickCurrentActiveJobId, type Status } from "../lib/status";

// Sentinel for lastAutoSelectedRef: the user explicitly closed the detail
// pane, so the auto-open must stay off until the page reloads. Never
// collides with a real job id (ids are positive).
const USER_CLOSED = -1;

export function useAutoSelectJob(
  downloads: ReadonlyArray<{ id: number; status: string }> | undefined,
  /** Selection restored from the URL — treated like a manual pick. */
  initialId: number | null = null,
): {
  selectedId: number | null;
  /** True when the selection came from the user (pick or deep link), not the auto-open. */
  isManualSelection: boolean;
  /** Manual selection (or close, with null) — exempt from auto-advance. */
  selectJob: (id: number | null) => void;
} {
  const [selectedId, setSelectedId] = useState<number | null>(initialId);
  const [isManualSelection, setIsManualSelection] = useState(initialId !== null);
  const lastAutoSelectedRef = useRef<number | null>(null);

  useEffect(() => {
    if (!downloads) return;
    const current = pickCurrentActiveJobId(downloads);
    if (current === null) return;

    if (selectedId === null) {
      if (lastAutoSelectedRef.current === null) {
        lastAutoSelectedRef.current = current;
        setIsManualSelection(false);
        setSelectedId(current);
      }
      return;
    }

    if (selectedId === lastAutoSelectedRef.current && current !== selectedId) {
      const sel = downloads.find((d) => d.id === selectedId);
      if (sel && isTerminal(sel.status as Status)) {
        lastAutoSelectedRef.current = current;
        setSelectedId(current);
      }
    }
  }, [downloads, selectedId]);

  const selectJob = (id: number | null) => {
    // Manual picks and closes take the selection out of auto-advance
    // custody: null re-arms nothing (USER_CLOSED blocks the auto-open),
    // and a manual pick must not be advanced away from — even if it's the
    // same id the auto-select last chose.
    lastAutoSelectedRef.current = id === null ? USER_CLOSED : null;
    setIsManualSelection(id !== null);
    setSelectedId(id);
  };

  return { selectedId, isManualSelection, selectJob };
}
