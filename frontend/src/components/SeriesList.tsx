import { Button, Select, TextInput, Tooltip, VisuallyHidden } from "@mantine/core";
import { memo, useMemo } from "react";
import { pollWatchedTargetsMutation } from "../api/@tanstack/react-query.gen";
import type { Target } from "../api/types.gen";
import { useDataInvalidators } from "../lib/invalidate";
import {
  displayName,
  LIBRARY_CHIPS,
  LIBRARY_SORTS,
  type LibraryFilters,
  type LibrarySort,
  matchesChip,
  sourcesOf,
} from "../lib/library";
import { FINISHED_SERIES_STATUSES } from "../lib/seriesStatus";
import { isActive, jobStatusLabel } from "../lib/status";
import { formatRel } from "../lib/time";
import { useNotifyingMutation } from "../lib/useNotifyingMutation";
import { AddSeriesBar } from "./AddSeriesBar";
import { EmptyState } from "./EmptyState";
import { ICON_SIZE, IconEye, IconLibrary, IconRefresh, IconSearch } from "./Icons";
import { Pill } from "./Pill";

/**
 * The library's list pane: add bar, search / sort / source, quick-filter
 * chips and one compact row per series. The list scrolls inside the pane
 * (or with the page on phones), so filters and the add bar stay in view.
 */
export function SeriesList({
  targets,
  visible,
  filters,
  onFiltersChange,
  selectedId,
  onSelect,
  isLoading,
}: {
  targets: ReadonlyArray<Target>;
  visible: ReadonlyArray<Target>;
  filters: LibraryFilters;
  onFiltersChange: (next: LibraryFilters) => void;
  selectedId: number | null;
  onSelect: (id: number) => void;
  isLoading: boolean;
}) {
  const set = (patch: Partial<LibraryFilters>) => onFiltersChange({ ...filters, ...patch });
  const sources = useMemo(() => sourcesOf(targets), [targets]);
  const chipCounts = useMemo(
    () =>
      Object.fromEntries(
        LIBRARY_CHIPS.map((c) => [c.value, targets.filter((t) => matchesChip(t, c.value)).length]),
      ),
    [targets],
  );
  const shownChapters = visible.reduce((n, t) => n + (t.chapter_count ?? 0), 0);
  const filtered = visible.length !== targets.length;

  return (
    <section className="lib-pane lib-list" aria-label="Series">
      <AddSeriesBar />
      <div className="lib-list-tools">
        <TextInput
          className="lib-list-search"
          aria-label="Search series by name, URL or tag"
          placeholder={`Search ${targets.length} series`}
          leftSection={<IconSearch size={ICON_SIZE.sm} />}
          value={filters.search}
          onChange={(e) => set({ search: e.currentTarget.value })}
        />
        <Select
          aria-label="Sort series"
          data={LIBRARY_SORTS.map((s) => ({ value: s.value, label: s.label }))}
          value={filters.sort}
          onChange={(v) => set({ sort: (v as LibrarySort) ?? "recent" })}
          allowDeselect={false}
          w={112}
          comboboxProps={{ withinPortal: true }}
        />
      </div>
      <fieldset className="lib-chips">
        <VisuallyHidden component="legend">Show series</VisuallyHidden>
        {LIBRARY_CHIPS.map((c) => (
          <button
            key={c.value}
            type="button"
            className="lib-chip"
            aria-pressed={filters.chip === c.value}
            title={c.hint}
            onClick={() => set({ chip: c.value })}
          >
            {c.label} <span className="lib-chip-count">{chipCounts[c.value]}</span>
          </button>
        ))}
        {sources.length > 1 && (
          <Select
            size="xs"
            className="lib-chips-source"
            aria-label="Filter by source"
            data={[
              { value: "", label: "All sources" },
              ...sources.map((s) => ({ value: s, label: s })),
            ]}
            value={filters.source ?? ""}
            onChange={(v) => set({ source: v ? v : null })}
            allowDeselect={false}
            w={128}
            comboboxProps={{ withinPortal: true }}
          />
        )}
      </fieldset>
      <div className="lib-list-meta">
        <span>
          {filtered ? `${visible.length} of ${targets.length} series` : `${targets.length} series`}
          {shownChapters > 0 ? ` · ${shownChapters.toLocaleString()} ch` : ""}
        </span>
        <RefreshWatchedButton targets={targets} />
      </div>
      <div className="lib-list-scroll">
        {visible.map((t) => (
          <SeriesListItem
            key={t.id}
            target={t}
            selected={t.id === selectedId}
            onSelect={onSelect}
          />
        ))}
        {!isLoading && targets.length === 0 && (
          <EmptyState
            icon={<IconLibrary size={ICON_SIZE.hero} />}
            title="Your library is empty"
            body="Paste a gallery URL above to add a series. Watched series are polled for new chapters on a schedule."
            arrow
          />
        )}
        {targets.length > 0 && visible.length === 0 && (
          <EmptyState compact title="No series match these filters" />
        )}
      </div>
    </section>
  );
}

const SeriesListItem = memo(function SeriesListItem({
  target: t,
  selected,
  onSelect,
}: {
  target: Target;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  const status = t.last_status ?? null;
  const pending = t.epub_pending_count ?? 0;
  const allExported = (t.epub_book_count ?? 0) > 0 && pending === 0;
  const meta = [t.extractor, t.series_status?.toLowerCase(), formatRel(t.last_finished_at)]
    .filter((v) => v && v !== "—")
    .join(" · ");
  return (
    <button
      type="button"
      className="lib-item"
      aria-current={selected ? "true" : undefined}
      onClick={() => onSelect(t.id)}
    >
      <span className="lib-item-line">
        <span className="lib-item-name">{displayName(t)}</span>
        <span className="lib-item-count">
          {t.chapter_count != null ? `${t.chapter_count} ch` : "—"}
        </span>
      </span>
      <span className="lib-item-line">
        <span className="lib-item-meta">{meta || "never downloaded"}</span>
        <span className="lib-item-badges">
          {status !== null && isActive(status) && (
            <Pill tone="active">{jobStatusLabel(status)}</Pill>
          )}
          {status === "failed" && <Pill tone="error">failed</Pill>}
          {pending > 0 && (
            <Pill tone="warn" noDot>
              {pending} to export
            </Pill>
          )}
          {allExported && (
            <Pill tone="done" noDot>
              EPUB ✓
            </Pill>
          )}
          {t.watched && (
            <span className="lib-item-watched" title="Watched">
              <IconEye size={ICON_SIZE.sm} />
              <VisuallyHidden>Watched</VisuallyHidden>
            </span>
          )}
        </span>
      </span>
    </button>
  );
});

function RefreshWatchedButton({ targets }: { targets: ReadonlyArray<Target> }) {
  const invalidate = useDataInvalidators();
  const refresh = useNotifyingMutation(
    {
      ...pollWatchedTargetsMutation(),
      onSuccess: () => {
        invalidate.targets();
        invalidate.downloads();
      },
    },
    {
      success: {
        title: "Refresh scheduled",
        message: (res) =>
          res.skipped_active > 0
            ? `${res.scheduled} series queued · ${res.skipped_active} skipped (already downloading)`
            : `${res.scheduled} series queued`,
        color: "blue",
      },
      error: { title: "Refresh failed" },
    },
  );
  // Mirrors the backend's poll-watched eligibility so the button can say up
  // front when a refresh would be a no-op.
  const refreshable = targets.filter(
    (t) => t.watched && !FINISHED_SERIES_STATUSES.includes(t.series_status ?? ""),
  ).length;
  if (targets.length === 0) return null;
  return (
    <Tooltip
      label={
        refreshable === 0
          ? "No watched series are expecting chapters right now"
          : `Poll the ${refreshable} watched series still expecting chapters`
      }
      withArrow
    >
      <Button
        size="compact-xs"
        variant="subtle"
        leftSection={<IconRefresh size={ICON_SIZE.xs} />}
        loading={refresh.isPending}
        // aria-disabled (not native disabled) keeps the button hoverable so
        // the tooltip can explain why it's inert; the click is guarded.
        aria-disabled={refreshable === 0 || undefined}
        data-disabled={refreshable === 0 || undefined}
        onClick={() => {
          if (refreshable > 0) refresh.mutate({});
        }}
      >
        Refresh watched
      </Button>
    </Tooltip>
  );
}
