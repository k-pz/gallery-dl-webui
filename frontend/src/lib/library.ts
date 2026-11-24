import type { Target } from "../api/types.gen";
import { makeNeedleMatcher } from "./listFilters";
import { isActive } from "./status";

/** Quick filters above the series list. */
export type LibraryChip = "all" | "watched" | "active" | "failed" | "export" | "nobooks";

export const LIBRARY_CHIPS: ReadonlyArray<{ value: LibraryChip; label: string; hint: string }> = [
  { value: "all", label: "All", hint: "Every series" },
  { value: "watched", label: "Watched", hint: "Polled for new chapters on a schedule" },
  { value: "active", label: "Active", hint: "A download is queued or running" },
  { value: "failed", label: "Failed", hint: "The last download failed" },
  { value: "export", label: "To export", hint: "EPUB books never exported or outdated" },
  { value: "nobooks", label: "No books", hint: "Chapters on disk but no EPUB books yet" },
];

export function matchesChip(t: Target, chip: LibraryChip): boolean {
  switch (chip) {
    case "watched":
      return t.watched;
    case "active":
      return t.last_status != null && isActive(t.last_status);
    case "failed":
      return t.last_status === "failed";
    case "export":
      return (t.epub_pending_count ?? 0) > 0;
    case "nobooks":
      return (t.chapter_count ?? 0) > 0 && t.epub_book_count === 0;
    default:
      return true;
  }
}

export type LibrarySort = "recent" | "name" | "chapters" | "added";

export const LIBRARY_SORTS: ReadonlyArray<{ value: LibrarySort; label: string }> = [
  { value: "recent", label: "Recent" },
  { value: "name", label: "Name" },
  { value: "chapters", label: "Chapters" },
  { value: "added", label: "Added" },
];

/** Most recent activity: last finished run, else last queued, else added. */
export function recencyKey(t: Target): number {
  for (const v of [t.last_finished_at, t.last_created_at, t.created_at]) {
    if (!v) continue;
    const n = Date.parse(v);
    if (!Number.isNaN(n)) return n;
  }
  return 0;
}

export function displayName(t: Target): string {
  return t.name ?? t.url;
}

export type LibraryFilters = {
  search: string;
  chip: LibraryChip;
  source: string | null;
  sort: LibrarySort;
};

export const DEFAULT_LIBRARY_FILTERS: LibraryFilters = {
  search: "",
  chip: "all",
  source: null,
  sort: "recent",
};

/** Filter by search (name, URL, tags), chip and source; then sort. */
export function visibleTargets(targets: ReadonlyArray<Target>, f: LibraryFilters): Target[] {
  const needle = makeNeedleMatcher<Target>(
    f.search,
    (t) => t.name,
    (t) => t.url,
    (t) => (t.tags ?? []).join(" "),
  );
  const out = targets.filter(
    (t) => needle(t) && matchesChip(t, f.chip) && (f.source === null || t.extractor === f.source),
  );
  const byName = (a: Target, b: Target) =>
    displayName(a).localeCompare(displayName(b), undefined, { sensitivity: "base" });
  switch (f.sort) {
    case "name":
      return out.sort(byName);
    case "chapters":
      return out.sort((a, b) => (b.chapter_count ?? -1) - (a.chapter_count ?? -1) || byName(a, b));
    case "added":
      return out.sort((a, b) => b.created_at.localeCompare(a.created_at));
    default:
      return out.sort((a, b) => recencyKey(b) - recencyKey(a));
  }
}

export function sourcesOf(targets: ReadonlyArray<Target>): string[] {
  const names = new Set<string>();
  for (const t of targets) if (t.extractor) names.add(t.extractor);
  return [...names].sort();
}
