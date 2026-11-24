import { VisuallyHidden } from "@mantine/core";
import { type KeyboardEvent, memo, useMemo, useRef } from "react";
import type { BookState, PackChapter } from "../lib/epubPacker";

export type MapBook = {
  key: string;
  position: number;
  state: BookState;
  chapters: PackChapter[];
};

/**
 * Every chapter of the series as a small block, grouped by book and coloured
 * by the book's export state, so a series of hundreds of chapters fits in a
 * few rows. Clicking a block selects that chapter; the packer's inspector
 * then offers to split or merge there.
 *
 * Keyboard: the map is one tab stop (roving tabindex on the selected
 * chapter); arrow keys move the selection, Home/End jump to the ends.
 */
export const ChapterMap = memo(function ChapterMap({
  books,
  looseChapters,
  selected,
  onSelect,
}: {
  books: ReadonlyArray<MapBook>;
  /** Shown as one unassigned group when there are no books yet. */
  looseChapters: ReadonlyArray<PackChapter>;
  selected: number | null;
  onSelect: (value: number) => void;
}) {
  const rootRef = useRef<HTMLFieldSetElement | null>(null);
  const groups = useMemo(
    () =>
      books.length > 0
        ? books
        : [{ key: "loose", position: 0, state: "empty" as const, chapters: [...looseChapters] }],
    [books, looseChapters],
  );
  const values = useMemo(() => groups.flatMap((g) => g.chapters.map((c) => c.value)), [groups]);
  const focusValue = selected !== null && values.includes(selected) ? selected : values[0];

  const move = (e: KeyboardEvent<HTMLFieldSetElement>) => {
    const keys: Record<string, (i: number) => number> = {
      ArrowRight: (i) => i + 1,
      ArrowDown: (i) => i + 1,
      ArrowLeft: (i) => i - 1,
      ArrowUp: (i) => i - 1,
      Home: () => 0,
      End: () => values.length - 1,
    };
    const step = keys[e.key];
    if (!step || values.length === 0) return;
    e.preventDefault();
    const current = Math.max(values.indexOf(focusValue ?? values[0]), 0);
    const next = values[Math.min(Math.max(step(current), 0), values.length - 1)];
    onSelect(next);
    rootRef.current?.querySelector<HTMLButtonElement>(`[data-value="${next}"]`)?.focus();
  };

  return (
    <fieldset ref={rootRef} className="chmap" onKeyDown={move}>
      <VisuallyHidden component="legend">
        Chapter map. Arrow keys move between chapters.
      </VisuallyHidden>
      {groups.map((g) => (
        <span
          key={g.key}
          className="chmap-book"
          data-selected={
            selected !== null && g.chapters.some((c) => c.value === selected) && g.position > 0
              ? "true"
              : undefined
          }
          title={g.position > 0 ? `Book ${g.position}` : "Not in a book"}
        >
          {g.chapters.map((c) => (
            <button
              key={c.number}
              type="button"
              className="chmap-cell"
              data-state={g.position > 0 ? g.state : "loose"}
              data-value={c.value}
              aria-pressed={c.value === selected}
              aria-label={`Chapter ${c.number}${g.position > 0 ? `, book ${g.position}` : ""}`}
              title={`c${c.number}${c.title ? ` · ${c.title}` : ""}${c.volume ? ` · Vol. ${c.volume}` : ""}`}
              tabIndex={c.value === focusValue ? 0 : -1}
              onClick={() => onSelect(c.value)}
            />
          ))}
        </span>
      ))}
    </fieldset>
  );
});
