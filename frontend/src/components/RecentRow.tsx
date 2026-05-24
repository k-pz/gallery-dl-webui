import { Box, Group, Stack, Text, Tooltip } from "@mantine/core";
import type { Download } from "../api/types.gen";
import { CANCELLING_LABEL, isCancellable, isTerminal, jobStep, statusTone } from "../lib/status";
import { IconRefresh, IconX } from "./Icons";
import { Pill } from "./Pill";

function chapterCountLabel(item: Download): string {
  const total = item.chapters_total;
  if (total == null) return "—";
  const packed = item.postprocess_chapters_packed;
  if (packed != null) return `${packed}/${total} ch.`;
  return `${total} ch.`;
}

export function RecentRow({
  item,
  selected,
  cancelling,
  inflight,
  isCancelPending,
  isRequeuePending,
  onSelect,
  onCancel,
  onRequeue,
}: {
  item: Download;
  selected: boolean;
  cancelling: boolean;
  inflight: boolean;
  isCancelPending: boolean;
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
    <Box
      className="app-row"
      data-selected={selected ? "true" : undefined}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(item.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(item.id);
        }
      }}
    >
      <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
        <div className="app-row-line">
          <Pill tone={tone}>{step.label}</Pill>
          <Text size="xs" c="dimmed" ff="monospace">
            #{item.id}
          </Text>
          <Text className="app-row-name" size="sm" fw={selected ? 600 : 500} title={displayName}>
            {displayName}
          </Text>
          <Text size="xs" c="dimmed" ff="monospace" style={{ whiteSpace: "nowrap" }}>
            {chapterCountLabel(item)}
          </Text>
        </div>
        {showUrlSubtitle && (
          <Text className="app-url app-row-url" title={item.url}>
            {item.url}
          </Text>
        )}
      </Stack>
      <Group gap={2} wrap="nowrap" onClick={(e) => e.stopPropagation()}>
        {(canCancel || showCancelling) && (
          <Tooltip label={showCancelling ? "Cancelling…" : "Cancel"} withArrow>
            <button
              type="button"
              className="icon-btn"
              data-tone="danger"
              data-size="sm"
              aria-label={`Cancel #${item.id}`}
              disabled={inflight || showCancelling || (inflight && isCancelPending)}
              onClick={onCancel}
            >
              <IconX size={14} />
            </button>
          </Tooltip>
        )}
        {isTerminal(item.status) && (
          <Tooltip label="Requeue" withArrow>
            <button
              type="button"
              className="icon-btn"
              data-tone="accent"
              data-size="sm"
              aria-label={`Requeue #${item.id}`}
              disabled={inflight && isRequeuePending}
              onClick={onRequeue}
            >
              <IconRefresh size={14} />
            </button>
          </Tooltip>
        )}
      </Group>
    </Box>
  );
}
