import type { EpubBookIn, EpubBookOut, EpubChapterOut } from "../api/types.gen";
import type { PillTone } from "../components/Pill";

/**
 * One editable row of the EPUB book editor. Range bounds are kept as the
 * raw input strings so partially typed values ("12.") survive re-renders;
 * they're parsed only on save. An empty `end` means open-ended.
 */
export type DraftBook = {
  key: string;
  title: string;
  start: string;
  end: string;
};

let draftCounter = 0;
function nextKey(): string {
  draftCounter += 1;
  return `draft-${draftCounter}`;
}

/** 1 → "1", 2.5 → "2.5" (JS number formatting drops a trailing ".0"). */
export function formatChapterNumber(value: number): string {
  return String(value);
}

export function draftsFromBooks(books: ReadonlyArray<EpubBookOut>): DraftBook[] {
  return books.map((b) => ({
    key: `book-${b.id}`,
    title: b.custom_title ?? "",
    start: formatChapterNumber(b.chapter_start),
    end: b.chapter_end == null ? "" : formatChapterNumber(b.chapter_end),
  }));
}

export function draftsFromSuggestion(books: ReadonlyArray<EpubBookIn>): DraftBook[] {
  return books.map((b) => ({
    key: nextKey(),
    title: b.title ?? "",
    start: formatChapterNumber(b.chapter_start),
    end: b.chapter_end == null ? "" : formatChapterNumber(b.chapter_end),
  }));
}

function parseNumber(raw: string): number | null {
  const cleaned = raw.trim();
  if (cleaned === "") return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : Number.NaN;
}

/**
 * Turn the draft rows into the PUT payload, or a user-facing error for
 * input the server would reject anyway (non-numeric or missing bounds).
 * Overlap/ordering rules are left to the server, which owns them.
 */
export function parseDrafts(
  drafts: ReadonlyArray<DraftBook>,
): { books: EpubBookIn[] } | { error: string } {
  const books: EpubBookIn[] = [];
  for (const [i, d] of drafts.entries()) {
    const start = parseNumber(d.start);
    if (start === null || Number.isNaN(start)) {
      return { error: `Book ${i + 1}: enter the chapter number it starts at.` };
    }
    const end = parseNumber(d.end);
    if (Number.isNaN(end)) {
      return { error: `Book ${i + 1}: the end chapter must be a number (or empty).` };
    }
    books.push({ title: d.title.trim() || null, chapter_start: start, chapter_end: end });
  }
  return { books };
}

/** True when the drafts describe exactly the saved books (same order). */
export function draftsMatchBooks(
  drafts: ReadonlyArray<DraftBook>,
  books: ReadonlyArray<EpubBookOut>,
): boolean {
  if (drafts.length !== books.length) return false;
  return drafts.every((d, i) => {
    const b = books[i];
    return (
      d.title.trim() === (b.custom_title ?? "") &&
      parseNumber(d.start) === b.chapter_start &&
      parseNumber(d.end) === (b.chapter_end ?? null)
    );
  });
}

/**
 * A fresh row starting at the first chapter after every closed book. When a
 * book is still open-ended its range is ambiguous, so the start is left for
 * the user to fill in.
 */
export function newDraftAfter(
  drafts: ReadonlyArray<DraftBook>,
  chapters: ReadonlyArray<EpubChapterOut>,
): DraftBook {
  const blank = { key: nextKey(), title: "", start: "", end: "" };
  if (drafts.some((d) => d.end.trim() === "")) return blank;
  const ends = drafts.map((d) => parseNumber(d.end)).filter((v): v is number => v !== null);
  const maxEnd = ends.length > 0 ? Math.max(...ends) : Number.NEGATIVE_INFINITY;
  const next = chapters
    .map((c) => Number(c.number))
    .filter((v) => Number.isFinite(v) && v > maxEnd)
    .sort((a, b) => a - b)[0];
  return next === undefined ? blank : { ...blank, start: formatChapterNumber(next) };
}

export function defaultBookTitle(series: string | null | undefined, position: number): string {
  return series ? `${series}, Vol. ${position}` : `Vol. ${position}`;
}

const STATUS: Record<EpubBookOut["status"], { label: string; tone: PillTone }> = {
  empty: { label: "no chapters", tone: "muted" },
  not_exported: { label: "not exported", tone: "info" },
  outdated: { label: "outdated", tone: "warn" },
  exported: { label: "exported", tone: "done" },
};

export function bookStatus(status: EpubBookOut["status"]): { label: string; tone: PillTone } {
  return STATUS[status];
}

/** "c1–c12" for a book's actual first/last chapters on disk. */
export function bookChapterSpan(book: EpubBookOut): string | null {
  if (!book.first_chapter || !book.last_chapter) return null;
  return book.first_chapter === book.last_chapter
    ? `c${book.first_chapter}`
    : `c${book.first_chapter}–c${book.last_chapter}`;
}

export function epubFileUrl(targetId: number, bookId: number): string {
  return `/api/targets/${targetId}/epub/books/${bookId}/file`;
}
