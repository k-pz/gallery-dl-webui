import { describe, expect, it } from "vitest";
import type { Target } from "../api/types.gen";
import { DEFAULT_LIBRARY_FILTERS, matchesChip, sourcesOf, visibleTargets } from "./library";

function target(overrides: Partial<Target>): Target {
  return {
    id: 1,
    url: "https://example/a",
    name: "Alpha",
    extractor: "mangadex",
    output_dir: null,
    watched: false,
    watch_period: null,
    last_polled_at: null,
    created_at: "2026-01-01T00:00:00+00:00",
    tags: [],
    ...overrides,
  };
}

const LIBRARY = [
  target({
    id: 1,
    name: "Alpha",
    watched: true,
    chapter_count: 120,
    epub_book_count: 12,
    epub_pending_count: 3,
    last_finished_at: "2026-03-01T00:00:00+00:00",
  }),
  target({
    id: 2,
    name: "beta",
    extractor: "mangapark",
    chapter_count: 800,
    epub_book_count: 0,
    epub_pending_count: 0,
    last_status: "failed",
    tags: ["romance"],
    last_finished_at: "2026-05-01T00:00:00+00:00",
  }),
  target({
    id: 3,
    name: null,
    url: "https://example/gamma",
    last_status: "running",
    created_at: "2026-06-01T00:00:00+00:00",
  }),
];

describe("matchesChip", () => {
  it("filters by watch, activity, failure and EPUB state", () => {
    const ids = (chip: Parameters<typeof matchesChip>[1]) =>
      LIBRARY.filter((t) => matchesChip(t, chip)).map((t) => t.id);
    expect(ids("all")).toEqual([1, 2, 3]);
    expect(ids("watched")).toEqual([1]);
    expect(ids("active")).toEqual([3]);
    expect(ids("failed")).toEqual([2]);
    expect(ids("export")).toEqual([1]);
    // Unscanned series (null counts) don't count as "no books".
    expect(ids("nobooks")).toEqual([2]);
  });
});

describe("visibleTargets", () => {
  it("searches names, URLs and tags", () => {
    const find = (search: string) =>
      visibleTargets(LIBRARY, { ...DEFAULT_LIBRARY_FILTERS, search }).map((t) => t.id);
    expect(find("ALP")).toEqual([1]);
    expect(find("gamma")).toEqual([3]);
    expect(find("romance")).toEqual([2]);
  });

  it("sorts by recency, name, chapters and date added", () => {
    const sorted = (sort: (typeof DEFAULT_LIBRARY_FILTERS)["sort"]) =>
      visibleTargets(LIBRARY, { ...DEFAULT_LIBRARY_FILTERS, sort }).map((t) => t.id);
    expect(sorted("recent")).toEqual([3, 2, 1]);
    expect(sorted("name")).toEqual([1, 2, 3]);
    expect(sorted("chapters")).toEqual([2, 1, 3]);
    expect(sorted("added")).toEqual([3, 1, 2]);
  });

  it("filters by source", () => {
    const only = visibleTargets(LIBRARY, { ...DEFAULT_LIBRARY_FILTERS, source: "mangapark" });
    expect(only.map((t) => t.id)).toEqual([2]);
    expect(sourcesOf(LIBRARY)).toEqual(["mangadex", "mangapark"]);
  });
});
