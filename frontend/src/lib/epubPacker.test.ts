import { describe, expect, it } from "vitest";
import type { EpubBookOut, EpubChapterOut } from "../api/types.gen";
import {
  bookIndex,
  chapterSpan,
  type DraftBook,
  draftsFromBooks,
  draftsFromStarts,
  isDirty,
  mergeWithNext,
  mergeWithPrevious,
  numberedChapters,
  packingMode,
  planBooks,
  splitAt,
  startsEveryN,
  toPayload,
  unnumberedChapters,
} from "./epubPacker";

function chapter(number: string, overrides: Partial<EpubChapterOut> = {}): EpubChapterOut {
  return {
    number,
    title: "",
    volume: "",
    pages: 10,
    file_name: `S - c${number}.cbz`,
    book_position: null,
    ...overrides,
  };
}

function book(overrides: Partial<EpubBookOut>): EpubBookOut {
  return {
    id: 1,
    position: 1,
    title: "S, Vol. 1",
    custom_title: null,
    chapter_start: 1,
    chapter_count: 0,
    page_count: 0,
    first_chapter: null,
    last_chapter: null,
    status: "not_exported",
    exported_at: null,
    file_name: null,
    ...overrides,
  };
}

const draft = (start: number, title = ""): DraftBook => ({ key: `k${start}`, start, title });

const CHAPTERS = numberedChapters(["1", "2", "2.5", "3", "4", "5", "Extra"].map((n) => chapter(n)));

describe("numberedChapters / unnumberedChapters", () => {
  it("keeps numeric chapters in order and sets the others aside", () => {
    expect(CHAPTERS.map((c) => c.value)).toEqual([1, 2, 2.5, 3, 4, 5]);
    expect(unnumberedChapters([chapter("2"), chapter("Extra")])).toEqual(["Extra"]);
  });
});

describe("bookIndex", () => {
  it("puts every number in exactly one book", () => {
    const starts = [3, 10];
    expect([1, 3, 9.5, 10, 99].map((v) => bookIndex(v, starts))).toEqual([0, 0, 0, 1, 1]);
  });
});

describe("planBooks", () => {
  it("splits chapters at the starts and gives the first book earlier chapters", () => {
    const plan = planBooks([draft(2), draft(4)], CHAPTERS, []);
    expect(plan.map((b) => b.chapters.map((c) => c.number))).toEqual([
      ["1", "2", "2.5", "3"],
      ["4", "5"],
    ]);
    expect(plan.map((b) => b.pages)).toEqual([40, 20]);
    expect(plan.every((b) => b.state === "unsaved")).toBe(true);
  });

  it("keeps the saved status while start, position, chapters and title still match", () => {
    const saved = [
      book({
        id: 7,
        chapter_start: 1,
        chapter_count: 4,
        first_chapter: "1",
        last_chapter: "3",
        status: "exported",
      }),
    ];
    expect(planBooks([draft(1), draft(4)], CHAPTERS, saved)[0].state).toBe("exported");
    // A new chapter shifts the book's content → unsaved until saved again.
    expect(planBooks([draft(1), draft(3)], CHAPTERS, saved)[0].state).toBe("unsaved");
    // A changed title too.
    expect(planBooks([draft(1, "New"), draft(4)], CHAPTERS, saved)[0].state).toBe("unsaved");
  });
});

describe("editing", () => {
  it("splits at a chapter, keeping titles of existing books", () => {
    const next = splitAt([draft(1, "First")], CHAPTERS, 3);
    expect(next?.map((d) => [d.start, d.title])).toEqual([
      [1, "First"],
      [3, ""],
    ]);
  });

  it("refuses a split at an existing start or one that empties a book", () => {
    expect(splitAt([draft(1), draft(3)], CHAPTERS, 3)).toBeNull();
    // The book starting at 3.5 holds chapters 4 and 5; splitting at 4 would
    // leave it with nothing.
    expect(splitAt([draft(1), draft(3.5)], CHAPTERS, 4)).toBeNull();
    // Splitting chapter 1 off a book that starts at 2 is fine: chapter 1 got
    // there only because the first book takes earlier chapters.
    expect(splitAt([draft(2)], CHAPTERS, 1)?.map((d) => d.start)).toEqual([1, 2]);
  });

  it("merges with the previous or next book", () => {
    const drafts = [draft(1), draft(3), draft(5)];
    expect(mergeWithPrevious(drafts, 1)?.map((d) => d.start)).toEqual([1, 5]);
    expect(mergeWithNext(drafts, 1)?.map((d) => d.start)).toEqual([1, 3]);
    expect(mergeWithPrevious(drafts, 0)).toBeNull();
    expect(mergeWithNext(drafts, 2)).toBeNull();
  });

  it("builds starts every N chapters on disk", () => {
    expect(startsEveryN(CHAPTERS, 2)).toEqual([1, 2.5, 4]);
  });

  it("reuses drafts for starts that stay", () => {
    const current = [draft(1, "Keep"), draft(4)];
    const next = draftsFromStarts([4, 1, 2], current);
    expect(next.map((d) => d.start)).toEqual([1, 2, 4]);
    expect(next[0]).toBe(current[0]);
    expect(next[2]).toBe(current[1]);
  });
});

describe("saving", () => {
  const saved = [
    book({ id: 1, chapter_start: 1, custom_title: "One" }),
    book({ id: 2, position: 2, chapter_start: 4 }),
  ];

  it("detects edits against the saved books", () => {
    const drafts = draftsFromBooks(saved);
    expect(isDirty(drafts, saved)).toBe(false);
    expect(isDirty([drafts[0]], saved)).toBe(true);
    expect(isDirty([{ ...drafts[0], title: "Two" }, drafts[1]], saved)).toBe(true);
  });

  it("sends starts and trimmed titles", () => {
    expect(toPayload([draft(1, "  One "), draft(4, " ")])).toEqual([
      { chapter_start: 1, title: "One" },
      { chapter_start: 4, title: null },
    ]);
  });
});

describe("labels", () => {
  it("names the packing rule the books follow", () => {
    const volumes = [1, 3];
    expect(packingMode([draft(1), draft(3)], volumes, [1, 2.5, 4])).toBe("volume");
    expect(packingMode([draft(1), draft(2.5), draft(4)], volumes, [1, 2.5, 4])).toBe("fixed");
    expect(packingMode([draft(1)], volumes, [1, 2.5, 4])).toBe("manual");
  });

  it("renders chapter spans", () => {
    expect(chapterSpan(CHAPTERS.slice(0, 3))).toBe("c1–c2.5");
    expect(chapterSpan(CHAPTERS.slice(0, 1))).toBe("c1");
    expect(chapterSpan([])).toBe("—");
  });
});
