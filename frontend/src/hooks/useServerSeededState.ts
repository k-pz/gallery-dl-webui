/**
 * Input state seeded from a server value.
 *
 * Forms that mirror a persisted value need three things at once: pre-fill
 * from the server (including late/refetched arrivals), let the user type
 * without each keystroke firing a request, and never clobber in-progress
 * edits when an unrelated invalidation refetches the backing query. This
 * hook centralises that dance: the value tracks `serverValue` until the
 * first user edit marks it dirty, and `markClean()` (call it once a save
 * lands) hands control back to the server.
 */

import { useEffect, useState } from "react";

export function useServerSeededState<T>(serverValue: T): {
  /** Current input value — server-seeded until the first user edit. */
  value: T;
  /** User edit: updates the value and freezes re-seeding. */
  setValue: (next: T) => void;
  /** True after a user edit, until `markClean` is called. */
  dirty: boolean;
  /** Hand the value back to the server, e.g. once a save lands. */
  markClean: () => void;
  /** Programmatic value change (optimistic reset) — dirtiness unchanged. */
  overwrite: (next: T) => void;
} {
  const [value, setValue] = useState<T>(serverValue);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) setValue(serverValue);
  }, [serverValue, dirty]);

  return {
    value,
    setValue: (next: T) => {
      setDirty(true);
      setValue(next);
    },
    dirty,
    markClean: () => setDirty(false),
    overwrite: setValue,
  };
}
