/**
 * Build a predicate that matches when a needle appears in any of the supplied
 * string fields (case-insensitive). Empty/whitespace needles match everything.
 *
 *   const m = makeNeedleMatcher(search, (t) => t.name, (t) => t.url);
 *   items.filter(m);
 */
export function makeNeedleMatcher<T>(
  needle: string,
  ...fields: ReadonlyArray<(item: T) => string | null | undefined>
): (item: T) => boolean {
  const cleaned = needle.trim().toLowerCase();
  if (!cleaned) return () => true;
  return (item: T) => {
    for (const get of fields) {
      const value = get(item);
      if (value?.toLowerCase().includes(cleaned)) return true;
    }
    return false;
  };
}
