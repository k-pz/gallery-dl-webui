import {
  Anchor,
  Box,
  Group,
  Select,
  Switch,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import {
  deleteTargetMutation,
  pollTargetMutation,
  updateTargetMutation,
} from "../api/@tanstack/react-query.gen";
import type { Target } from "../api/types.gen";
import { useServerSeededState } from "../hooks/useServerSeededState";
import { extractErrorMessage } from "../lib/apiError";
import { DURATION_FORMAT_HINT, isValidDuration } from "../lib/duration";
import { useDataInvalidators } from "../lib/invalidate";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { SERIES_STATUS_OPTIONS, seriesStatusTone } from "../lib/seriesStatus";
import { isActive, jobStatusLabel, statusTone } from "../lib/status";
import { formatRel } from "../lib/time";
import { useNotifyingMutation } from "../lib/useNotifyingMutation";
import { CopyIconButton } from "./CopyIconButton";
import { IconArrowUpRight, IconChevronDown, IconEye, IconPlay, IconTrash } from "./Icons";
import { InlineConfirm } from "./InlineConfirm";
import { Pill } from "./Pill";

export function recencyKey(t: Target): number {
  const candidates = [t.last_finished_at, t.last_created_at, t.created_at];
  for (const v of candidates) {
    if (!v) continue;
    const n = Date.parse(v);
    if (!Number.isNaN(n)) return n;
  }
  return 0;
}

export function TargetRow({
  target,
  defaultPeriod,
  onOpenJob,
  expanded,
  onToggle,
}: {
  target: Target;
  defaultPeriod: string;
  onOpenJob?: (jobId: number) => void;
  expanded: boolean;
  onToggle: () => void;
}) {
  const invalidate = useDataInvalidators();
  const period = useServerSeededState(target.watch_period ?? "");
  const [periodError, setPeriodError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const update = useMutation({
    ...updateTargetMutation(),
    onSuccess: () => {
      period.markClean();
      setPeriodError(null);
      invalidate.targets();
    },
    onError: (err, vars) => {
      // Only period submissions render inline under the "Poll every" field;
      // a failed tags / status / watch update would otherwise surface its
      // error under an unrelated input (or go unnoticed entirely).
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

  const poll = useNotifyingMutation(
    {
      ...pollTargetMutation(),
      onSuccess: () => invalidate.targets(),
    },
    {
      success: {
        title: "Poll queued",
        message: `Queued a fresh job for ${target.url}`,
        color: "blue",
      },
      error: { title: "Poll failed" },
    },
  );

  const del = useNotifyingMutation(
    {
      ...deleteTargetMutation(),
      onSuccess: () => invalidate.targets(),
    },
    {
      success: { title: "Series removed", message: target.url, color: "gray" },
      error: { title: "Remove failed" },
    },
  );

  const submitPeriod = () => {
    if (!period.dirty) return;
    // Validate locally before the round-trip — same grammar as the backend
    // (an empty value is fine: it clears the override).
    if (period.value.trim() !== "" && !isValidDuration(period.value)) {
      setPeriodError(DURATION_FORMAT_HINT);
      return;
    }
    setPeriodError(null);
    update.mutate({
      path: { target_id: target.id },
      body: { watch_period: period.value },
    });
  };

  const status = target.last_status ?? "pending";
  const tone = statusTone(status);
  const busy = update.isPending || poll.isPending || del.isPending;
  const displayName = target.name ?? target.url;
  const tags = target.tags ?? [];
  const downloadCount = target.download_count ?? 0;
  const lastDownloadId = target.last_download_id ?? null;

  return (
    <article className="lib-row" data-expanded={expanded ? "true" : undefined}>
      {/* The head's click handler is a pointer-only convenience (bigger
          target); the canonical, keyboard- and screen-reader-reachable
          toggle is the chevron button on the right. Keeping the div free of
          role/tabindex avoids nesting the action buttons inside a control. */}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: pointer-only convenience — the chevron button is the accessible toggle */}
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: see above */}
      <div className="lib-row-head" onClick={onToggle}>
        <div className="lib-row-main">
          <div className="lib-row-top">
            <div className="lib-row-pills">
              {target.series_status && (
                <Pill tone={seriesStatusTone(target.series_status)}>{target.series_status}</Pill>
              )}
              {isActive(status) && <Pill tone={tone}>{jobStatusLabel(status)}</Pill>}
              {target.watched && (
                <Group gap={4} wrap="nowrap" style={{ color: "var(--app-accent)" }}>
                  <IconEye size={11} />
                  <Text size="xs" component="span" style={{ color: "inherit" }}>
                    watched
                  </Text>
                </Group>
              )}
            </div>
            <Text className="lib-row-name" size="sm" fw={500} ff="monospace" title={displayName}>
              {displayName}
            </Text>
            <Text
              size="xs"
              c="dimmed"
              ff="monospace"
              className="lib-row-meta"
              style={{ letterSpacing: "0.04em" }}
            >
              {target.extractor ?? "—"} · {downloadCount}
              {downloadCount === 1 ? " run" : " runs"} · {formatRel(target.last_finished_at) ?? "—"}
            </Text>
          </div>
          {tags.length > 0 && (
            <Group gap={4} wrap="wrap" className="lib-row-tags">
              {tags.slice(0, 3).map((t) => (
                <span key={t} className="code-chip" style={{ background: "transparent" }}>
                  {t}
                </span>
              ))}
              {tags.length > 3 && (
                <Text size="xs" c="dimmed">
                  +{tags.length - 3}
                </Text>
              )}
            </Group>
          )}
        </div>
        <Group
          className="lib-row-actions"
          gap={2}
          wrap="nowrap"
          onClick={(e) => e.stopPropagation()}
        >
          {lastDownloadId !== null && onOpenJob && (
            <Anchor
              size="xs"
              component="button"
              type="button"
              style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "0 6px" }}
              onClick={() => onOpenJob(lastDownloadId)}
            >
              job #{lastDownloadId} <IconArrowUpRight size={11} />
            </Anchor>
          )}
          <Tooltip label="Poll now" withArrow>
            <button
              type="button"
              className="icon-btn"
              data-tone="accent"
              data-size="sm"
              disabled={busy}
              aria-label={`Poll target ${target.id}`}
              onClick={() => poll.mutate({ path: { target_id: target.id } })}
            >
              <IconPlay size={14} />
            </button>
          </Tooltip>
          <Tooltip label="Remove series" withArrow>
            <button
              type="button"
              className="icon-btn"
              data-tone="danger"
              data-size="sm"
              disabled={busy}
              aria-label={`Delete target ${target.id}`}
              onClick={() => {
                setConfirmingDelete(true);
                if (!expanded) onToggle();
              }}
            >
              <IconTrash size={14} />
            </button>
          </Tooltip>
          <button
            type="button"
            className="icon-btn"
            data-size="sm"
            aria-expanded={expanded}
            aria-label={expanded ? `Collapse ${displayName}` : `Expand ${displayName}`}
            onClick={onToggle}
          >
            <IconChevronDown size={14} className="lib-row-chev" />
          </button>
        </Group>
      </div>

      {expanded && (
        <div className="lib-row-body">
          {confirmingDelete && (
            <Box mb="md">
              <InlineConfirm
                confirmLabel="Remove"
                message={
                  <>
                    Remove <strong>{displayName}</strong> from the library? Files on disk stay;
                    you'll lose tags and the watch schedule.
                  </>
                }
                loading={del.isPending}
                onCancel={() => setConfirmingDelete(false)}
                onConfirm={() => {
                  del.mutate(
                    { path: { target_id: target.id } },
                    {
                      onSettled: () => setConfirmingDelete(false),
                    },
                  );
                }}
              />
            </Box>
          )}
          <Group gap="md" align="flex-end" wrap="wrap">
            <Switch
              label="Watch"
              checked={target.watched}
              disabled={update.isPending}
              onChange={(e) =>
                update.mutate({
                  path: { target_id: target.id },
                  body: { watched: e.currentTarget.checked },
                })
              }
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
                target.watch_period
                  ? "Per-target override. Clear to fall back."
                  : `Default: ${defaultPeriod}`
              }
              miw={150}
              style={{ flex: "1 1 170px" }}
              error={periodError ?? undefined}
            />
            <Select
              label="Reading direction"
              value={target.reading_direction ?? ""}
              data={[{ value: "", label: "Use default" }, ...READING_DIRECTION_OPTIONS]}
              onChange={(v) =>
                update.mutate({
                  path: { target_id: target.id },
                  body: { reading_direction: v ?? "" },
                })
              }
              disabled={update.isPending}
              miw={150}
              style={{ flex: "1 1 180px" }}
              comboboxProps={{ withinPortal: true }}
              allowDeselect={false}
            />
            <Select
              label="Series status"
              value={target.series_status ?? ""}
              data={[{ value: "", label: "Unknown" }, ...SERIES_STATUS_OPTIONS]}
              onChange={(v) =>
                update.mutate({
                  path: { target_id: target.id },
                  body: { series_status: v ?? "" },
                })
              }
              disabled={update.isPending}
              miw={150}
              style={{ flex: "1 1 160px" }}
              comboboxProps={{ withinPortal: true }}
              allowDeselect={false}
            />
          </Group>
          <Box mt="sm">
            <TagsInput
              label="Tags"
              placeholder="Enter to add"
              value={tags}
              onChange={(next) =>
                update.mutate({
                  path: { target_id: target.id },
                  body: { tags: next },
                })
              }
              disabled={update.isPending}
              clearable
            />
          </Box>
          <Group gap={4} wrap="nowrap" align="center" mt={12}>
            <Anchor href={target.url} target="_blank" rel="noreferrer" className="app-url">
              {target.url}
            </Anchor>
            <CopyIconButton value={target.url} label="Copy URL" />
          </Group>
        </div>
      )}
    </article>
  );
}
