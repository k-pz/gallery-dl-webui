import { useEffect, useMemo, useState } from "react";

export const DEFAULT_PAGE_SIZE = 10;

/**
 * Slice `items` into a single visible page. The current page resets to 1 when
 * `resetKey` changes (callers pass a serialized filter/sort key so page 1
 * shows after the user narrows the list). It also clamps when the underlying
 * total shrinks below the current page.
 */
export function usePagination<T>(
  items: readonly T[],
  resetKey: string,
  pageSize: number = DEFAULT_PAGE_SIZE,
) {
  const [page, setPage] = useState(1);

  // biome-ignore lint/correctness/useExhaustiveDependencies: resetKey is the reactive trigger.
  useEffect(() => {
    setPage(1);
  }, [resetKey]);

  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * pageSize;
  const pageItems = useMemo(() => items.slice(start, start + pageSize), [items, start, pageSize]);

  return {
    page: safePage,
    setPage,
    totalPages,
    pageSize,
    pageItems,
    start,
    end: Math.min(start + pageSize, total),
    total,
  };
}
