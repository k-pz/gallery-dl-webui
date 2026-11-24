import { Select, Switch, TagsInput, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getConfigOptions, updateTargetMutation } from "../api/@tanstack/react-query.gen";
import type { Target } from "../api/types.gen";
import { useServerSeededState } from "../hooks/useServerSeededState";
import { extractErrorMessage } from "../lib/apiError";
import { DURATION_FORMAT_HINT, isValidDuration } from "../lib/duration";
import { useDataInvalidators } from "../lib/invalidate";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { SERIES_STATUS_OPTIONS } from "../lib/seriesStatus";
import { formatAbs, formatDate, formatRel } from "../lib/time";

/** At-a-glance figures for a series, shown above its settings. */
export function SeriesStats({ target: t }: { target: Target }) {
  const books = t.epub_book_count ?? null;
  const pending = t.epub_pending_count ?? 0;
  const stats: { label: string; value: string; sub: string }[] = [
    {
      label: "Chapters",
      value: t.chapter_count != null ? t.chapter_count.toLocaleString() : "—",
      sub: t.chapter_count != null ? "packed on disk" : "not scanned yet",
    },
    {
      label: "EPUB books",
      value: books != null ? String(books) : "—",
      sub: books ? (pending > 0 ? `${pending} to export` : "all exported") : "none defined",
    },
    {
      label: "Runs",
      value: String(t.download_count ?? 0),
      sub: t.last_finished_at ? `last ${formatRel(t.last_finished_at)}` : "never finished",
    },
    {
      label: "Published",
      value: formatDate(t.series_published_at),
      sub: `added ${formatAbs(t.created_at)}`,
    },
  ];
  return (
    <div className="series-stats">
      {stats.map((s) => (
        <div key={s.label} className="series-stat">
          <span className="series-stat-label">{s.label}</span>
          <span className="series-stat-value">{s.value}</span>
          <span className="series-stat-sub">{s.sub}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Editable per-series settings. Each field saves on its own (toggle/select
 * on change, text fields on blur or Enter), so there is no form-level save.
 */
export function SeriesSettings({ target }: { target: Target }) {
  const invalidate = useDataInvalidators();
  const { data: config } = useQuery(getConfigOptions());
  const defaultPeriod = config?.default_watch_period ?? "1d";
  const period = useServerSeededState(target.watch_period ?? "");
  const metaSource = useServerSeededState(target.metadata_source_url ?? "");
  const [periodError, setPeriodError] = useState<string | null>(null);

  const update = useMutation({
    ...updateTargetMutation(),
    onSuccess: () => {
      period.markClean();
      metaSource.markClean();
      setPeriodError(null);
      invalidate.targets();
    },
    onError: (err, vars) => {
      // Period errors render under the "Poll every" field; anything else
      // would otherwise land under an unrelated input, so notify instead.
      if (vars.body && "watch_period" in vars.body) {
        setPeriodError(extractErrorMessage(err));
      } else {
        notifications.show({
          title: "Update failed",
          message: extractErrorMessage(err),
          color: "red",
        });
      }
    },
  });
  const patch = (body: NonNullable<Parameters<typeof update.mutate>[0]["body"]>) =>
    update.mutate({ path: { target_id: target.id }, body });

  const submitPeriod = () => {
    if (!period.dirty) return;
    // Same grammar as the backend; an empty value clears the override.
    if (period.value.trim() !== "" && !isValidDuration(period.value)) {
      setPeriodError(DURATION_FORMAT_HINT);
      return;
    }
    setPeriodError(null);
    patch({ watch_period: period.value });
  };
  const submitMetaSource = () => {
    if (!metaSource.dirty) return;
    patch({ metadata_source_url: metaSource.value.trim() });
  };

  return (
    <div className="series-settings">
      <div className="series-settings-watch">
        <Switch
          label="Watch"
          checked={target.watched}
          disabled={update.isPending}
          onChange={(e) => patch({ watched: e.currentTarget.checked })}
        />
        <TextInput
          label="Poll every"
          placeholder={defaultPeriod}
          value={period.value}
          disabled={!target.watched || update.isPending}
          onChange={(e) => period.setValue(e.currentTarget.value)}
          onBlur={submitPeriod}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitPeriod();
          }}
          description={
            target.watch_period ? "Override; clear to use the default" : `Default: ${defaultPeriod}`
          }
          error={periodError ?? undefined}
          className="series-settings-grow"
        />
      </div>
      <Select
        label="Reading direction"
        value={target.reading_direction ?? ""}
        data={[{ value: "", label: "Use default" }, ...READING_DIRECTION_OPTIONS]}
        onChange={(v) => patch({ reading_direction: v ?? "" })}
        disabled={update.isPending}
        comboboxProps={{ withinPortal: true }}
        allowDeselect={false}
      />
      <Select
        label="Series status"
        value={target.series_status ?? ""}
        data={[{ value: "", label: "Unknown" }, ...SERIES_STATUS_OPTIONS]}
        onChange={(v) => patch({ series_status: v ?? "" })}
        disabled={update.isPending}
        comboboxProps={{ withinPortal: true }}
        allowDeselect={false}
      />
      <TagsInput
        label="Tags"
        placeholder="Enter to add"
        value={target.tags ?? []}
        onChange={(next) => patch({ tags: next })}
        disabled={update.isPending}
        clearable
      />
      <TextInput
        label="Metadata source URL"
        placeholder="https://mangadex.org/title/…"
        value={metaSource.value}
        disabled={update.isPending}
        onChange={(e) => metaSource.setValue(e.currentTarget.value)}
        onBlur={submitMetaSource}
        onKeyDown={(e) => {
          if (e.key === "Enter") submitMetaSource();
        }}
        description="Another site for this series (e.g. MangaDex), used to fill chapter titles this source lacks."
        className="series-settings-wide"
      />
      <Text size="xs" c="dimmed" className="series-settings-wide">
        Changes save as you make them.
      </Text>
    </div>
  );
}
