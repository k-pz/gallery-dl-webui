import {
  Alert,
  Button,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  exportTargetEpubBookMutation,
  exportTargetEpubBooksMutation,
  getTargetEpubOptions,
  getTargetEpubQueryKey,
  putTargetEpubBooksMutation,
} from "../api/@tanstack/react-query.gen";
import type { EpubOverview } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import {
  bookIndex,
  bookStateLabel,
  chapterSpan,
  type DraftBook,
  defaultBookTitle,
  draftsFromBooks,
  draftsFromStarts,
  epubFileUrl,
  isDirty,
  mergeWithNext,
  mergeWithPrevious,
  numberedChapters,
  type PackingMode,
  packingMode,
  planBooks,
  splitAt,
  startsEveryN,
  startsFromSuggestion,
  toPayload,
  unnumberedChapters,
} from "../lib/epubPacker";
import { ChapterMap, type MapBook } from "./ChapterMap";
import { ICON_SIZE, IconDownload, IconX } from "./Icons";
import { Pill } from "./Pill";

// Unsaved book edits per series, kept for the session so picking another
// series and coming back doesn't throw them away.
const draftCache = new Map<number, DraftBook[]>();

/** Forget every unsaved edit (tests start from a clean slate). */
export function clearPackerDrafts(): void {
  draftCache.clear();
}

type ListFilter = "all" | "todo" | "done";

/**
 * The EPUB packer for one series: a chapter map, the packing rule, the book
 * list and the save/export bar. Books split the series at their start
 * chapters, so every numbered chapter is always in exactly one book; edits
 * are split points, with chapter and page counts updated before saving.
 */
export function EpubPacker({ targetId }: { targetId: number }) {
  const query = useQuery(getTargetEpubOptions({ path: { target_id: targetId } }));
  if (query.isLoading) {
    return (
      <Group gap="xs" p="md">
        <Loader size="xs" />
        <Text size="sm" c="dimmed">
          Reading chapters…
        </Text>
      </Group>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Alert color="red" variant="light" m="md">
        {extractErrorMessage(query.error)}
      </Alert>
    );
  }
  if (!query.data.series) {
    return (
      <Text size="sm" c="dimmed" p="md">
        This series hasn't been downloaded yet, so there is nothing to pack.
      </Text>
    );
  }
  return <PackerBody targetId={targetId} data={query.data} />;
}

function PackerBody({ targetId, data }: { targetId: number; data: EpubOverview }) {
  const qc = useQueryClient();
  const queryKey = getTargetEpubQueryKey({ path: { target_id: targetId } });
  const [drafts, setDraftState] = useState<DraftBook[] | null>(
    () => draftCache.get(targetId) ?? null,
  );
  const [selected, setSelected] = useState<number | null>(null);
  const [filter, setFilter] = useState<ListFilter>("all");
  const [everyN, setEveryN] = useState(10);
  const [chosenMode, setChosenMode] = useState<PackingMode | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const setDrafts = (next: DraftBook[] | null) => {
    if (next) draftCache.set(targetId, next);
    else draftCache.delete(targetId);
    setFormError(null);
    setDraftState(next);
  };

  const chapters = useMemo(() => numberedChapters(data.chapters), [data.chapters]);
  const loose = useMemo(() => unnumberedChapters(data.chapters), [data.chapters]);
  const rows = useMemo(() => drafts ?? draftsFromBooks(data.books), [drafts, data.books]);
  const dirty = drafts !== null && isDirty(drafts, data.books);
  const plan = useMemo(() => planBooks(rows, chapters, data.books), [rows, chapters, data.books]);
  const volumeStarts = useMemo(
    () => startsFromSuggestion(data.suggested_books),
    [data.suggested_books],
  );
  const mode = chosenMode ?? packingMode(rows, volumeStarts, startsEveryN(chapters, everyN));

  const save = useMutation({
    ...putTargetEpubBooksMutation(),
    onSuccess: (overview) => {
      qc.setQueryData(queryKey, overview);
      setDrafts(null);
      setChosenMode(null);
    },
    onError: (err) => setFormError(extractErrorMessage(err)),
  });
  const exportOne = useMutation({
    ...exportTargetEpubBookMutation(),
    onSuccess: (overview, vars) => {
      qc.setQueryData(queryKey, overview);
      const book = overview.books.find((b) => b.id === vars.path.book_id);
      notifications.show({
        title: "EPUB exported",
        message: book?.file_name ?? "Book exported",
        color: "green",
      });
    },
    onError: (err) =>
      notifications.show({
        title: "Export failed",
        message: extractErrorMessage(err),
        color: "red",
      }),
  });
  const exportAll = useMutation({
    ...exportTargetEpubBooksMutation(),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey });
      notifications.show({
        title: result.failed ? "EPUB export finished with errors" : "EPUB export finished",
        message: result.failed
          ? `${result.exported} exported, ${result.failed} failed — ${result.errors[0]}`
          : `${result.exported} book${result.exported === 1 ? "" : "s"} exported`,
        color: result.failed ? "yellow" : "green",
      });
    },
    onError: (err) =>
      notifications.show({
        title: "Export failed",
        message: extractErrorMessage(err),
        color: "red",
      }),
  });
  const busy = save.isPending || exportOne.isPending || exportAll.isPending;

  const starts = rows.map((d) => d.start);
  const selectedBook = selected !== null && rows.length > 0 ? bookIndex(selected, starts) : -1;
  const selectedChapter = chapters.find((c) => c.value === selected);
  const split = selected !== null ? splitAt(rows, chapters, selected) : null;

  const applyStarts = (next: number[]) => setDrafts(draftsFromStarts(next, rows));
  const changeMode = (value: string) => {
    const next = value as PackingMode;
    setChosenMode(next);
    if (next === "volume") applyStarts(volumeStarts);
    if (next === "fixed") applyStarts(startsEveryN(chapters, everyN));
  };
  const edit = (next: DraftBook[] | null) => {
    if (!next) return;
    setChosenMode("manual");
    setDrafts(next);
  };

  const counts = { exported: 0, outdated: 0, not_exported: 0, unsaved: 0, empty: 0 };
  for (const b of plan) counts[b.state] += 1;
  const pending = counts.outdated + counts.not_exported;
  const mapBooks: MapBook[] = plan.map((b) => ({
    key: b.draft.key,
    position: b.position,
    state: b.state,
    chapters: b.chapters,
  }));
  const shown = plan.filter((b) =>
    filter === "all" ? true : filter === "done" ? b.state === "exported" : b.state !== "exported",
  );
  const changed = plan.filter((b) => b.state === "unsaved").length;

  return (
    <div className="packer">
      <div className="packer-toolbar">
        <span className="app-section-kicker">Packing</span>
        <SegmentedControl
          size="xs"
          value={mode}
          onChange={changeMode}
          disabled={busy || chapters.length === 0}
          aria-label="Packing rule"
          data={[
            {
              value: "volume",
              label: `By volume${volumeStarts.length ? ` (${volumeStarts.length})` : ""}`,
              disabled: volumeStarts.length === 0,
            },
            { value: "fixed", label: "Every N chapters" },
            { value: "manual", label: "Manual" },
          ]}
        />
        {mode === "fixed" && (
          <NumberInput
            size="xs"
            w={92}
            min={1}
            max={500}
            value={everyN}
            aria-label="Chapters per book"
            suffix=" ch"
            onChange={(v) => {
              const n = typeof v === "number" && v >= 1 ? v : 1;
              setEveryN(n);
              applyStarts(startsEveryN(chapters, n));
            }}
          />
        )}
        <Text size="xs" c="dimmed" className="packer-toolbar-meta">
          {chapters.length} chapters
          {volumeStarts.length > 0 ? ` · ${volumeStarts.length} books by volume` : " · no volumes"}
        </Text>
      </div>

      <div className="packer-map">
        <ChapterMap
          books={mapBooks}
          looseChapters={chapters}
          selected={selected}
          onSelect={setSelected}
        />
        <div className="packer-legend">
          <Legend state="exported" label="Exported" count={counts.exported} />
          <Legend state="outdated" label="Outdated" count={counts.outdated} />
          <Legend state="not_exported" label="Not exported" count={counts.not_exported} />
          {counts.unsaved > 0 && <Legend state="unsaved" label="Unsaved" count={counts.unsaved} />}
          {loose.length > 0 && (
            <Text size="xs" c="dimmed">
              Not numbered, so in no book: {loose.join(", ")}
            </Text>
          )}
        </div>
      </div>

      <div className="packer-inspector" aria-live="polite">
        {selectedChapter ? (
          <>
            <Text size="sm" className="packer-inspector-text">
              <strong>c{selectedChapter.number}</strong>
              <span className="packer-dim">
                {selectedChapter.volume ? ` · Vol. ${selectedChapter.volume}` : " · no volume"}
                {selectedChapter.title ? ` · ${selectedChapter.title}` : ""}
                {selectedBook >= 0
                  ? ` · in book ${selectedBook + 1} (${chapterSpan(plan[selectedBook].chapters)})`
                  : ""}
              </span>
            </Text>
            <Group gap={6} wrap="wrap" className="packer-inspector-actions">
              <Button
                size="compact-sm"
                variant="default"
                disabled={busy || !split}
                onClick={() => edit(split)}
              >
                {rows.length === 0
                  ? "Put all chapters in one book"
                  : `Start a new book at c${selectedChapter.number}`}
              </Button>
              <Button
                size="compact-sm"
                variant="default"
                disabled={busy || selectedBook < 1}
                onClick={() => edit(mergeWithPrevious(rows, selectedBook))}
              >
                Merge with previous
              </Button>
              <Button
                size="compact-sm"
                variant="default"
                disabled={busy || selectedBook < 0 || selectedBook >= rows.length - 1}
                onClick={() => edit(mergeWithNext(rows, selectedBook))}
              >
                Merge with next
              </Button>
              <button
                type="button"
                className="icon-btn"
                data-size="sm"
                aria-label="Clear chapter selection"
                onClick={() => setSelected(null)}
              >
                <IconX size={ICON_SIZE.sm} />
              </button>
            </Group>
          </>
        ) : (
          <Text size="sm" c="dimmed">
            {rows.length === 0
              ? "No books yet. Pick a packing rule above, or click a chapter to start from it."
              : "Click a chapter on the map to start a new book there or merge its book with a neighbour."}
          </Text>
        )}
      </div>

      <div className="packer-listhead">
        <SegmentedControl
          size="xs"
          value={filter}
          onChange={(v) => setFilter(v as ListFilter)}
          aria-label="Show books"
          data={[
            { value: "all", label: `All ${plan.length}` },
            { value: "todo", label: `To export ${plan.length - counts.exported}` },
            { value: "done", label: `Exported ${counts.exported}` },
          ]}
        />
      </div>
      <ul className="packer-list" aria-label="EPUB books">
        {shown.map((b) => {
          const idx = b.position - 1;
          const isLast = idx === plan.length - 1;
          const st = bookStateLabel(b.state);
          const exportable =
            !dirty && b.saved !== undefined && b.state !== "empty" && b.state !== "unsaved";
          return (
            <li
              key={b.draft.key}
              className="packer-row"
              data-selected={idx === selectedBook ? "true" : undefined}
            >
              <button
                type="button"
                className="packer-row-pos"
                aria-label={`Show book ${b.position} on the map`}
                onClick={() => setSelected(b.chapters[0]?.value ?? b.draft.start)}
              >
                #{b.position}
              </button>
              <TextInput
                size="xs"
                variant="unstyled"
                className="packer-row-title"
                aria-label={`Title of book ${b.position}`}
                placeholder={defaultBookTitle(data.series, b.position)}
                value={b.draft.title}
                disabled={busy}
                onChange={(e) => {
                  const title = e.currentTarget.value;
                  setDrafts(rows.map((d, i) => (i === idx ? { ...d, title } : d)));
                }}
              />
              <span className="packer-row-num">
                {chapterSpan(b.chapters)}
                {isLast && b.chapters.length > 0 ? " · open" : ""}
              </span>
              <span className="packer-row-num packer-dim">{b.chapters.length} ch</span>
              <span className="packer-row-num packer-dim">{b.pages.toLocaleString()} p</span>
              <span>
                <Pill tone={st.tone}>{st.label}</Pill>
              </span>
              <span className="packer-row-actions">
                <Tooltip
                  label={dirty ? "Save books first" : "Nothing to export"}
                  disabled={exportable}
                  withArrow
                >
                  <Button
                    size="compact-xs"
                    variant="light"
                    disabled={busy || !exportable}
                    onClick={() => {
                      if (b.saved)
                        exportOne.mutate({ path: { target_id: targetId, book_id: b.saved.id } });
                    }}
                  >
                    {b.state === "exported" ? "Re-export" : "Export"}
                  </Button>
                </Tooltip>
                {b.saved?.file_name ? (
                  <a
                    className="icon-btn"
                    data-size="sm"
                    data-tone="accent"
                    href={epubFileUrl(targetId, b.saved.id)}
                    download={b.saved.file_name}
                    aria-label={`Download book ${b.position}`}
                  >
                    <IconDownload size={ICON_SIZE.sm} />
                  </a>
                ) : (
                  <span className="packer-row-dl-slot" />
                )}
              </span>
            </li>
          );
        })}
        {plan.length === 0 && chapters.length > 0 && (
          <li className="packer-empty">
            <Text size="sm" fw={500}>
              No books yet
            </Text>
            <Group gap="xs" wrap="wrap">
              {volumeStarts.length > 0 && (
                <Button size="xs" onClick={() => changeMode("volume")} disabled={busy}>
                  One book per volume ({volumeStarts.length})
                </Button>
              )}
              <Button
                size="xs"
                variant="default"
                disabled={busy}
                onClick={() => changeMode("fixed")}
              >
                Every {everyN} chapters ({startsEveryN(chapters, everyN).length})
              </Button>
              <Button
                size="xs"
                variant="default"
                disabled={busy}
                onClick={() => edit(draftsFromStarts([chapters[0].value], []))}
              >
                One book for everything
              </Button>
            </Group>
          </li>
        )}
      </ul>
      {chapters.length === 0 && (
        <Text size="sm" c="dimmed" p="md">
          No packed chapters found
          {data.series_dir ? ` in ${data.series_dir}` : ""}.
        </Text>
      )}

      {formError && (
        <Alert color="red" variant="light" className="packer-error">
          {formError}
        </Alert>
      )}
      <div className="packer-foot">
        <Text size="sm" c="dimmed">
          {plan.length} book{plan.length === 1 ? "" : "s"} · {counts.exported} exported · {pending}{" "}
          to export
        </Text>
        <Text
          size="xs"
          c="dimmed"
          ff="monospace"
          className="packer-foot-path"
          title={data.export_dir}
        >
          → {data.export_dir}
        </Text>
        <div className="packer-foot-actions">
          {dirty ? (
            <>
              <Text size="sm" fw={500} className="packer-unsaved">
                {changed} book{changed === 1 ? "" : "s"} changed
              </Text>
              <Button
                variant="subtle"
                color="gray"
                disabled={busy}
                onClick={() => {
                  setDrafts(null);
                  setChosenMode(null);
                }}
              >
                Discard
              </Button>
              <Button
                loading={save.isPending}
                disabled={busy}
                onClick={() =>
                  save.mutate({ path: { target_id: targetId }, body: { books: toPayload(rows) } })
                }
              >
                Save books
              </Button>
            </>
          ) : (
            <Button
              loading={exportAll.isPending}
              disabled={busy || pending === 0}
              onClick={() => exportAll.mutate({ path: { target_id: targetId } })}
            >
              {pending === 0 ? "All books exported" : `Export ${pending} pending`}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function Legend({ state, label, count }: { state: string; label: string; count: number }) {
  return (
    <span className="packer-legend-item">
      <span className="chmap-swatch" data-state={state} aria-hidden="true" />
      {label} <span className="packer-legend-count">{count}</span>
    </span>
  );
}
