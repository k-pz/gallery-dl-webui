import { Alert, Anchor, Button, Group, Loader, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  exportTargetEpubBookMutation,
  exportTargetEpubBooksMutation,
  getTargetEpubOptions,
  getTargetEpubQueryKey,
  putTargetEpubBooksMutation,
} from "../api/@tanstack/react-query.gen";
import type { EpubBookOut, EpubOverview } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import {
  bookChapterSpan,
  bookStatus,
  type DraftBook,
  defaultBookTitle,
  draftsFromBooks,
  draftsFromSuggestion,
  draftsMatchBooks,
  epubFileUrl,
  newDraftAfter,
  parseDrafts,
} from "../lib/epubBooks";
import { formatAbs } from "../lib/time";
import { ICON_SIZE, IconDownload, IconPlus, IconTrash } from "./Icons";
import { Pill } from "./Pill";

const UNASSIGNED_PREVIEW = 12;

/**
 * Collapsible "EPUB books" section of an expanded library row. The overview
 * (which scans the series' CBZs on disk) is only fetched once opened.
 */
export function EpubBooksPanel({ targetId }: { targetId: number }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="epub-panel" aria-label="EPUB books">
      <Group justify="space-between" wrap="nowrap" gap="sm">
        <div>
          <Text size="sm" fw={500}>
            EPUB books
          </Text>
          <Text size="xs" c="dimmed">
            Group chapters into books and export them as EPUB (e.g. for Calibre).
          </Text>
        </div>
        <Button
          size="xs"
          variant="default"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          style={{ flexShrink: 0 }}
        >
          {open ? "Hide" : "Manage"}
        </Button>
      </Group>
      {open && <EpubBooksEditor targetId={targetId} />}
    </section>
  );
}

function EpubBooksEditor({ targetId }: { targetId: number }) {
  const qc = useQueryClient();
  const queryKey = getTargetEpubQueryKey({ path: { target_id: targetId } });
  const query = useQuery(getTargetEpubOptions({ path: { target_id: targetId } }));
  // null = no local edits; the rows mirror the saved books.
  const [drafts, setDrafts] = useState<DraftBook[] | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const setOverview = (overview: EpubOverview) => qc.setQueryData(queryKey, overview);

  const save = useMutation({
    ...putTargetEpubBooksMutation(),
    onSuccess: (overview) => {
      setOverview(overview);
      setDrafts(null);
      setFormError(null);
    },
    onError: (err) => setFormError(extractErrorMessage(err)),
  });

  const exportOne = useMutation({
    ...exportTargetEpubBookMutation(),
    onSuccess: (overview, vars) => {
      setOverview(overview);
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

  if (query.isLoading) {
    return (
      <Group gap="xs" mt="sm">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Reading chapters…
        </Text>
      </Group>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Alert color="red" variant="light" mt="sm">
        {extractErrorMessage(query.error)}
      </Alert>
    );
  }

  const data = query.data;
  if (!data.series) {
    return (
      <Text size="xs" c="dimmed" mt="sm">
        This series hasn't been downloaded yet, so there is nothing to export.
      </Text>
    );
  }

  const rows = drafts ?? draftsFromBooks(data.books);
  const dirty = drafts !== null && !draftsMatchBooks(drafts, data.books);
  const busy = save.isPending || exportOne.isPending || exportAll.isPending;
  const pending = data.books.filter((b) => b.status === "not_exported" || b.status === "outdated");

  const edit = (next: DraftBook[]) => {
    setFormError(null);
    setDrafts(next);
  };
  const updateRow = (index: number, patch: Partial<DraftBook>) =>
    edit(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));

  const submit = () => {
    const parsed = parseDrafts(rows);
    if ("error" in parsed) {
      setFormError(parsed.error);
      return;
    }
    save.mutate({ path: { target_id: targetId }, body: { books: parsed.books } });
  };

  return (
    <Stack gap="sm" mt="sm">
      <Text size="xs" c="dimmed">
        {data.chapters.length} chapter{data.chapters.length === 1 ? "" : "s"} on disk · exports to{" "}
        <Text span size="xs" ff="monospace">
          {data.export_dir}
        </Text>
      </Text>

      {data.chapters.length === 0 && (
        <Text size="xs" c="dimmed">
          No packed chapters found
          {data.series_dir ? (
            <>
              {" "}
              in{" "}
              <Text span size="xs" ff="monospace">
                {data.series_dir}
              </Text>
            </>
          ) : null}
          .
        </Text>
      )}

      {rows.map((row, i) => (
        <BookRow
          key={row.key}
          index={i}
          row={row}
          series={data.series}
          // Saved-state details only line up with the rows while unedited.
          book={dirty ? undefined : data.books[i]}
          targetId={targetId}
          disabled={busy}
          onChange={(patch) => updateRow(i, patch)}
          onRemove={() => edit(rows.filter((_, j) => j !== i))}
          onExport={(bookId) =>
            exportOne.mutate({ path: { target_id: targetId, book_id: bookId } })
          }
        />
      ))}

      {rows.length === 0 && data.chapters.length > 0 && (
        <Text size="xs" c="dimmed">
          No books yet. Add one, or start from the series' volumes.
        </Text>
      )}

      {formError && (
        <Alert color="red" variant="light">
          {formError}
        </Alert>
      )}

      <Group gap="xs" wrap="wrap">
        <Button
          size="xs"
          variant="default"
          leftSection={<IconPlus size={ICON_SIZE.xs} />}
          disabled={busy}
          onClick={() => edit([...rows, newDraftAfter(rows, data.chapters)])}
        >
          Add book
        </Button>
        {data.suggested_books.length > 0 && (
          <Button
            size="xs"
            variant="default"
            disabled={busy}
            onClick={() => edit(draftsFromSuggestion(data.suggested_books))}
          >
            Use volumes ({data.suggested_books.length})
          </Button>
        )}
        {dirty && (
          <>
            <Button size="xs" loading={save.isPending} disabled={busy} onClick={submit}>
              Save books
            </Button>
            <Button
              size="xs"
              variant="subtle"
              disabled={busy}
              onClick={() => {
                setDrafts(null);
                setFormError(null);
              }}
            >
              Discard
            </Button>
          </>
        )}
        {!dirty && pending.length > 0 && (
          <Button
            size="xs"
            variant="light"
            loading={exportAll.isPending}
            disabled={busy}
            onClick={() => exportAll.mutate({ path: { target_id: targetId } })}
          >
            Export {pending.length} pending
          </Button>
        )}
      </Group>

      {dirty && (
        <Text size="xs" c="dimmed">
          Save to update chapter counts and enable export.
        </Text>
      )}

      {!dirty && data.unassigned.length > 0 && (
        <Text size="xs" c="dimmed">
          Not in any book ({data.unassigned.length}):{" "}
          <Text span size="xs" ff="monospace">
            {data.unassigned
              .slice(0, UNASSIGNED_PREVIEW)
              .map((n) => `c${n}`)
              .join(", ")}
            {data.unassigned.length > UNASSIGNED_PREVIEW ? ", …" : ""}
          </Text>
        </Text>
      )}
    </Stack>
  );
}

function BookRow({
  index,
  row,
  series,
  book,
  targetId,
  disabled,
  onChange,
  onRemove,
  onExport,
}: {
  index: number;
  row: DraftBook;
  series: string | null | undefined;
  book: EpubBookOut | undefined;
  targetId: number;
  disabled: boolean;
  onChange: (patch: Partial<DraftBook>) => void;
  onRemove: () => void;
  onExport: (bookId: number) => void;
}) {
  const position = index + 1;
  const status = book ? bookStatus(book.status) : null;
  const span = book ? bookChapterSpan(book) : null;
  return (
    <div className="epub-book-row">
      <Group gap="xs" align="flex-end" wrap="wrap">
        <Text className="epub-book-index" size="sm" ff="monospace" c="dimmed">
          #{position}
        </Text>
        <TextInput
          size="xs"
          label="Title"
          placeholder={defaultBookTitle(series, position)}
          value={row.title}
          disabled={disabled}
          onChange={(e) => onChange({ title: e.currentTarget.value })}
          style={{ flex: "2 1 200px" }}
        />
        <TextInput
          size="xs"
          label="From chapter"
          inputMode="decimal"
          value={row.start}
          disabled={disabled}
          onChange={(e) => onChange({ start: e.currentTarget.value })}
          w={110}
        />
        <TextInput
          size="xs"
          label="To chapter"
          placeholder="latest"
          inputMode="decimal"
          value={row.end}
          disabled={disabled}
          onChange={(e) => onChange({ end: e.currentTarget.value })}
          w={110}
        />
        <button
          type="button"
          className="icon-btn"
          data-tone="danger"
          data-size="sm"
          disabled={disabled}
          aria-label={`Remove book ${position}`}
          onClick={onRemove}
        >
          <IconTrash size={ICON_SIZE.sm} />
        </button>
      </Group>
      {book && status && (
        <Group gap="sm" mt={6} wrap="wrap" align="center">
          <Pill tone={status.tone}>{status.label}</Pill>
          <Text size="xs" c="dimmed" ff="monospace">
            {book.chapter_count} ch · {book.page_count} pages{span ? ` · ${span}` : ""}
          </Text>
          {book.exported_at && (
            <Text size="xs" c="dimmed" title={book.exported_at}>
              exported {formatAbs(book.exported_at)}
            </Text>
          )}
          <Button
            size="compact-xs"
            variant="light"
            disabled={disabled || book.status === "empty"}
            onClick={() => onExport(book.id)}
          >
            {book.status === "exported" ? "Re-export" : "Export"}
          </Button>
          {book.file_name && (
            <Anchor
              size="xs"
              href={epubFileUrl(targetId, book.id)}
              download={book.file_name}
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              <IconDownload size={ICON_SIZE.xs} /> Download
            </Anchor>
          )}
        </Group>
      )}
    </div>
  );
}
