import { Box, Group, Stack, Text, Tooltip } from "@mantine/core";
import type { Download } from "../api/types.gen";
import { CANCELLING_LABEL, isCancellable, isTerminal, jobStep, statusTone } from "../lib/status";
import { ICON_SIZE, IconRotateCcw, IconX } from "./Icons";
import { Pill } from "./Pill";

function chapterCountLabel(item: Download): string {
  const total = item.chapters_total;
  if (total == null) return "—";
  const packed = item.postprocess_chapters_packed;
  const base = packed != null ? `${packed}/${total} chapters` : `${total} chapters`;
  const failed = item.chapters_failed ?? 0;
  return failed > 0 ? `${base} · ${failed} failed` : base;
}

export function RecentRow({
  item,
  selected,
  cancelling,
  inflight,
  isRequeuePending,
  onSelect,
  onCancel,
  onRequeue,
}: {
  item: Download;
  selected: boolean;
  cancelling: boolean;
  inflight: boolean;
  isRequeuePending: boolean;
  onSelect: (id: number) => void;
  onCancel: () => void;
  onRequeue: () => void;
}) {
  const showCancelling = cancelling;
  const displayStatus = showCancelling ? CANCELLING_LABEL : item.status;
  const step = jobStep(item.status, item.postprocess_status, showCancelling);
  const canCancel = isCancellable(item.status) && !showCancelling;
  const displayName = item.name ?? item.url;
  const showUrlSubtitle = Boolean(item.name);
  const tone = statusTone(displayStatus);

  return (
    <Box className="app-row" data-selected={selected ? "true" : undefined}>
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <div className="app-row-line">
          <Pill tone={tone}>{step.label}</Pill>
          <Text size="xs" c="dimmed" ff="monospace">
            #{item.id}
          </Text>
          {/* The name is the row's real control: its ::after stretches over
              the whole row (see .app-row-select), so clicking anywhere except
              the action buttons opens the details. */}
          <Text
            component="button"
            type="button"
            className="app-row-name app-row-select"
            size="sm"
            fw={selected ? 600 : 500}
            title={displayName}
            onClick={() => onSelect(item.id)}
          >
            {displayName}
          </Text>
          <Text size="xs" c="dimmed" ff="monospace">
            {chapterCountLabel(item)}
          </Text>
        </div>
        {showUrlSubtitle && (
          <Text className="app-url app-row-url" title={item.url}>
            {item.url}
          </Text>
        )}
      </Stack>
      <Group className="app-row-actions" gap={2} wrap="nowrap">
        {(canCancel || showCancelling) && (
          <Tooltip label={showCancelling ? "Cancelling…" : "Cancel"} withArrow>
            <button
              type="button"
              className="icon-btn"
              data-tone="danger"
              data-size="sm"
              aria-label={`Cancel #${item.id}`}
              disabled={inflight || showCancelling}
              onClick={onCancel}
            >
              <IconX size={ICON_SIZE.sm} />
            </button>
          </Tooltip>
        )}
        {isTerminal(item.status) && (
          <Tooltip label="Run again (requeue)" withArrow>
            <button
              type="button"
              className="icon-btn"
              data-tone="accent"
              data-size="sm"
              aria-label={`Run #${item.id} again`}
              disabled={inflight && isRequeuePending}
              onClick={onRequeue}
            >
              <IconRotateCcw size={ICON_SIZE.sm} />
            </button>
          </Tooltip>
        )}
      </Group>
    </Box>
  );
}
