import { describe, expect, it } from "vitest";
import type { EpubBookOut, EpubChapterOut } from "../api/types.gen";
import {
  bookChapterSpan,
  type DraftBook,
  defaultBookTitle,
  draftsFromBooks,
  draftsFromSuggestion,
  draftsMatchBooks,
  formatChapterNumber,
  newDraftAfter,
  parseDrafts,
} from "./epubBooks";

function book(overrides: Partial<EpubBookOut>): EpubBookOut {
  return {
    id: 1,
    position: 1,
    title: "S, Vol. 1",
    custom_title: null,
    chapter_start: 1,
    chapter_end: 10,
    chapter_count: 10,
    page_count: 200,
    first_chapter: "1",
    last_chapter: "10",
    status: "not_exported",
    exported_at: null,
    file_name: null,
    ...overrides,
  };
}

function chapter(number: string): EpubChapterOut {
  return {
    number,
    title: "",
    volume: "",
    pages: 1,
    file_name: `c${number}.cbz`,
    book_position: null,
  };
}

function draft(start: string, end: string, title = ""): DraftBook {
  return { key: `${start}-${end}`, title, start, end };
}

describe("formatChapterNumber", () => {
  it("drops the decimal for whole chapters", () => {
    expect(formatChapterNumber(3)).toBe("3");
    expect(formatChapterNumber(2.5)).toBe("2.5");
  });
});

describe("draftsFromBooks / draftsFromSuggestion", () => {
  it("maps open-ended books to an empty end and keeps custom titles", () => {
    const drafts = draftsFromBooks([
      book({ id: 1, custom_title: "Arc", chapter_start: 1, chapter_end: 2.5 }),
      book({ id: 2, chapter_start: 3, chapter_end: null }),
    ]);
    expect(drafts.map(({ title, start, end }) => ({ title, start, end }))).toEqual([
      { title: "Arc", start: "1", end: "2.5" },
      { title: "", start: "3", end: "" },
    ]);
  });

  it("gives suggestion rows unique keys", () => {
    const drafts = draftsFromSuggestion([
      { chapter_start: 1, chapter_end: 4 },
      { chapter_start: 5, chapter_end: null },
    ]);
    expect(new Set(drafts.map((d) => d.key)).size).toBe(2);
    expect(drafts[1].end).toBe("");
  });
});

describe("parseDrafts", () => {
  it("builds the payload with trimmed titles and null open ends", () => {
    expect(parseDrafts([draft(" 1 ", "10", "  First "), draft("11", "  ")])).toEqual({
      books: [
        { title: "First", chapter_start: 1, chapter_end: 10 },
        { title: null, chapter_start: 11, chapter_end: null },
      ],
    });
  });

  it("rejects a missing or non-numeric start", () => {
    expect(parseDrafts([draft("", "3")])).toEqual({
      error: "Book 1: enter the chapter number it starts at.",
    });
    expect(parseDrafts([draft("1", "2"), draft("abc", "")])).toEqual({
      error: "Book 2: enter the chapter number it starts at.",
    });
  });

  it("rejects a non-numeric end", () => {
    expect(parseDrafts([draft("1", "x")])).toEqual({
      error: "Book 1: the end chapter must be a number (or empty).",
    });
  });
});

describe("draftsMatchBooks", () => {
  const books = [book({ chapter_start: 1, chapter_end: 10, custom_title: "A" })];

  it("is true for unchanged rows (numeric equality, trimmed title)", () => {
    expect(draftsMatchBooks([draft("1.0", "10", " A ")], books)).toBe(true);
  });

  it("is false when a bound, the title, or the row count changes", () => {
    expect(draftsMatchBooks([draft("2", "10", "A")], books)).toBe(false);
    expect(draftsMatchBooks([draft("1", "", "A")], books)).toBe(false);
    expect(draftsMatchBooks([draft("1", "10", "B")], books)).toBe(false);
    expect(draftsMatchBooks([], books)).toBe(false);
  });
});

describe("newDraftAfter", () => {
  const chapters = ["1", "2", "2.5", "3", "7"].map(chapter);

  it("starts after the highest closed end", () => {
    expect(newDraftAfter([draft("1", "2")], chapters)).toMatchObject({ start: "2.5", end: "" });
  });

  it("starts at the first chapter when there are no books", () => {
    expect(newDraftAfter([], chapters).start).toBe("1");
  });

  it("leaves the start blank when a book is still open-ended", () => {
    expect(newDraftAfter([draft("1", "")], chapters).start).toBe("");
  });

  it("leaves the start blank when every chapter is covered", () => {
    expect(newDraftAfter([draft("1", "7")], chapters).start).toBe("");
  });
});

describe("labels", () => {
  it("defaultBookTitle mirrors the backend default", () => {
    expect(defaultBookTitle("Series", 2)).toBe("Series, Vol. 2");
    expect(defaultBookTitle(null, 2)).toBe("Vol. 2");
  });

  it("bookChapterSpan renders the actual chapters on disk", () => {
    expect(bookChapterSpan(book({ first_chapter: "1", last_chapter: "8" }))).toBe("c1–c8");
    expect(bookChapterSpan(book({ first_chapter: "4", last_chapter: "4" }))).toBe("c4");
    expect(bookChapterSpan(book({ first_chapter: null, last_chapter: null }))).toBeNull();
  });
});
