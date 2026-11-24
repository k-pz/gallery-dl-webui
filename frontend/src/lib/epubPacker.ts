import type { EpubBookIn, EpubBookOut, EpubChapterOut } from "../api/types.gen";
import type { PillTone } from "../components/Pill";

/**
 * Client-side model of the EPUB packer. Books split a series at their start
 * chapters, the same rule the backend applies (backend/epub/library.py):
 * a book holds every chapter from its start up to the next book's start, the
 * first book also takes lower-numbered chapters and the last one stays open.
 * Every numbered chapter therefore belongs to exactly one book, so editing
 * means adding or removing split points, and counts can be shown live before
 * saving.
 */

export type PackChapter = {
  number: string;
  value: number;
  title: string;
  volume: string;
  pages: number;
};

/** A book being edited. `title` is the raw input ("" = default title). */
export type DraftBook = { key: string; start: number; title: string };

export type BookState = EpubBookOut["status"] | "unsaved";

export type PlannedBook = {
  draft: DraftBook;
  position: number;
  chapters: PackChapter[];
  pages: number;
  /** The saved book this draft still matches (same start, position and chapters). */
  saved: EpubBookOut | undefined;
  state: BookState;
};

let keyCounter = 0;
function nextKey(): string {
  keyCounter += 1;
  return `draft-${keyCounter}`;
}

/** Chapters with a numeric number, in chapter order. */
export function numberedChapters(chapters: ReadonlyArray<EpubChapterOut>): PackChapter[] {
  return chapters
    .map((c) => ({ ...c, value: Number(c.number) }))
    .filter((c) => c.number.trim() !== "" && Number.isFinite(c.value))
    .sort((a, b) => a.value - b.value)
    .map((c) => ({
      number: c.number,
      value: c.value,
      title: c.title,
      volume: c.volume,
      pages: c.pages,
    }));
}

/** Chapters whose number isn't numeric ("Extra"); they can't be in a book. */
export function unnumberedChapters(chapters: ReadonlyArray<EpubChapterOut>): string[] {
  return chapters
    .filter((c) => c.number.trim() === "" || !Number.isFinite(Number(c.number)))
    .map((c) => c.number);
}

export function draftsFromBooks(books: ReadonlyArray<EpubBookOut>): DraftBook[] {
  return [...books]
    .sort((a, b) => a.chapter_start - b.chapter_start)
    .map((b) => ({ key: `book-${b.id}`, start: b.chapter_start, title: b.custom_title ?? "" }));
}

/**
 * Drafts for a new set of start chapters. A start that already has a draft
 * keeps it (and so its title); new starts get untitled drafts.
 */
export function draftsFromStarts(
  starts: ReadonlyArray<number>,
  current: ReadonlyArray<DraftBook>,
): DraftBook[] {
  const byStart = new Map(current.map((d) => [d.start, d]));
  return [...new Set(starts)]
    .sort((a, b) => a - b)
    .map((start) => byStart.get(start) ?? { key: nextKey(), start, title: "" });
}

/** Index of the book a chapter number falls in, for sorted `starts`. */
export function bookIndex(value: number, starts: ReadonlyArray<number>): number {
  let lo = 0;
  let hi = starts.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (starts[mid] <= value) lo = mid + 1;
    else hi = mid;
  }
  return Math.max(lo - 1, 0);
}

function bucket(
  drafts: ReadonlyArray<DraftBook>,
  chapters: ReadonlyArray<PackChapter>,
): PackChapter[][] {
  const out: PackChapter[][] = drafts.map(() => []);
  if (drafts.length === 0) return out;
  const starts = drafts.map((d) => d.start);
  for (const ch of chapters) out[bookIndex(ch.value, starts)].push(ch);
  return out;
}

/** Resolve drafts (sorted by start) against the chapters on disk. */
export function planBooks(
  drafts: ReadonlyArray<DraftBook>,
  chapters: ReadonlyArray<PackChapter>,
  saved: ReadonlyArray<EpubBookOut>,
): PlannedBook[] {
  const buckets = bucket(drafts, chapters);
  return drafts.map((draft, i) => {
    const inBook = buckets[i];
    const position = i + 1;
    const match = saved.find(
      (b) =>
        b.chapter_start === draft.start &&
        b.position === position &&
        b.chapter_count === inBook.length &&
        (b.first_chapter ?? null) === (inBook[0]?.number ?? null) &&
        (b.last_chapter ?? null) === (inBook.at(-1)?.number ?? null),
    );
    const titleKept = match !== undefined && (match.custom_title ?? "") === draft.title.trim();
    return {
      draft,
      position,
      chapters: inBook,
      pages: inBook.reduce((n, c) => n + c.pages, 0),
      saved: match,
      state: match && titleKept ? match.status : "unsaved",
    };
  });
}

/** True when the drafts differ from the saved books (starts or titles). */
export function isDirty(
  drafts: ReadonlyArray<DraftBook>,
  books: ReadonlyArray<EpubBookOut>,
): boolean {
  const saved = draftsFromBooks(books);
  if (saved.length !== drafts.length) return true;
  return drafts.some((d, i) => d.start !== saved[i].start || d.title.trim() !== saved[i].title);
}

export function toPayload(drafts: ReadonlyArray<DraftBook>): EpubBookIn[] {
  return drafts.map((d) => ({ chapter_start: d.start, title: d.title.trim() || null }));
}

function emptyBooks(drafts: ReadonlyArray<DraftBook>, chapters: ReadonlyArray<PackChapter>) {
  return bucket(drafts, chapters).filter((b) => b.length === 0).length;
}

/**
 * Start a new book at `value`. Returns null when a book already starts there
 * or when the split would leave a book without chapters.
 */
export function splitAt(
  drafts: ReadonlyArray<DraftBook>,
  chapters: ReadonlyArray<PackChapter>,
  value: number,
): DraftBook[] | null {
  if (drafts.some((d) => d.start === value)) return null;
  const next = draftsFromStarts([...drafts.map((d) => d.start), value], drafts);
  if (drafts.length > 0 && emptyBooks(next, chapters) > emptyBooks(drafts, chapters)) return null;
  return next;
}

/** Merge book `index` into the one before it (its start goes away). */
export function mergeWithPrevious(
  drafts: ReadonlyArray<DraftBook>,
  index: number,
): DraftBook[] | null {
  if (index <= 0 || index >= drafts.length) return null;
  return drafts.filter((_, i) => i !== index);
}

/** Merge the book after `index` into book `index`. */
export function mergeWithNext(drafts: ReadonlyArray<DraftBook>, index: number): DraftBook[] | null {
  return mergeWithPrevious(drafts, index + 1);
}

export function startsFromSuggestion(suggested: ReadonlyArray<EpubBookIn>): number[] {
  return suggested.map((b) => b.chapter_start);
}

/** A book every `n` chapters, counted over the chapters actually on disk. */
export function startsEveryN(chapters: ReadonlyArray<PackChapter>, n: number): number[] {
  const step = Math.max(1, Math.floor(n));
  const out: number[] = [];
  for (let i = 0; i < chapters.length; i += step) out.push(chapters[i].value);
  return out;
}

export type PackingMode = "volume" | "fixed" | "manual";

export function sameStarts(a: ReadonlyArray<number>, b: ReadonlyArray<number>): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/** Which rule the current books follow, for the packing control. */
export function packingMode(
  drafts: ReadonlyArray<DraftBook>,
  volumeStarts: ReadonlyArray<number>,
  everyN: ReadonlyArray<number>,
): PackingMode {
  const starts = drafts.map((d) => d.start);
  if (volumeStarts.length > 0 && sameStarts(starts, volumeStarts)) return "volume";
  if (starts.length > 0 && sameStarts(starts, everyN)) return "fixed";
  return "manual";
}

/** "c1–c9" for a book's first and last chapters. */
export function chapterSpan(chapters: ReadonlyArray<PackChapter>): string {
  if (chapters.length === 0) return "—";
  const first = chapters[0].number;
  const last = chapters[chapters.length - 1].number;
  return first === last ? `c${first}` : `c${first}–c${last}`;
}

export function defaultBookTitle(series: string | null | undefined, position: number): string {
  return series ? `${series}, Vol. ${position}` : `Vol. ${position}`;
}

const STATE: Record<BookState, { label: string; tone: PillTone }> = {
  empty: { label: "no chapters", tone: "muted" },
  not_exported: { label: "not exported", tone: "info" },
  outdated: { label: "outdated", tone: "warn" },
  exported: { label: "exported", tone: "done" },
  unsaved: { label: "unsaved", tone: "active" },
};

export function bookStateLabel(state: BookState): { label: string; tone: PillTone } {
  return STATE[state];
}

export function needsExport(state: BookState): boolean {
  return state === "not_exported" || state === "outdated";
}

export function epubFileUrl(targetId: number, bookId: number): string {
  return `/api/targets/${targetId}/epub/books/${bookId}/file`;
}
