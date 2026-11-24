import { Anchor, Button, Group, Text } from "@mantine/core";
import { useState } from "react";
import { deleteTargetMutation, pollTargetMutation } from "../api/@tanstack/react-query.gen";
import type { Target } from "../api/types.gen";
import { useDataInvalidators } from "../lib/invalidate";
import { displayName } from "../lib/library";
import { seriesStatusTone } from "../lib/seriesStatus";
import { isActive, jobStatusLabel, statusTone } from "../lib/status";
import { formatRel } from "../lib/time";
import { useNotifyingMutation } from "../lib/useNotifyingMutation";
import { CopyIconButton } from "./CopyIconButton";
import { ICON_SIZE, IconArrowUpRight, IconEye, IconPlay, IconTrash } from "./Icons";
import { InlineConfirm } from "./InlineConfirm";
import { Pill } from "./Pill";

/** Name, state and the series-level actions at the top of the detail pane. */
export function SeriesHeader({
  target,
  onOpenJob,
  onRemoved,
}: {
  target: Target;
  onOpenJob: (jobId: number) => void;
  onRemoved: () => void;
}) {
  const invalidate = useDataInvalidators();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const name = displayName(target);

  const poll = useNotifyingMutation(
    { ...pollTargetMutation(), onSuccess: () => invalidate.targets() },
    {
      success: { title: "Poll queued", message: `Queued a fresh job for ${name}`, color: "blue" },
      error: { title: "Poll failed" },
    },
  );
  const del = useNotifyingMutation(
    {
      ...deleteTargetMutation(),
      onSuccess: () => {
        invalidate.targets();
        onRemoved();
      },
    },
    {
      success: { title: "Series removed", message: name, color: "gray" },
      error: { title: "Remove failed" },
    },
  );

  const status = target.last_status ?? null;
  const lastJob = target.last_download_id ?? null;
  return (
    <div className="series-head">
      <div className="series-head-pills">
        {target.series_status && (
          <Pill tone={seriesStatusTone(target.series_status)}>{target.series_status}</Pill>
        )}
        {status !== null && (
          <Pill tone={statusTone(status)}>
            {isActive(status)
              ? jobStatusLabel(status)
              : `last run ${jobStatusLabel(status).toLowerCase()} ${formatRel(target.last_finished_at)}`}
          </Pill>
        )}
        {target.watched && (
          <Text size="xs" component="span" className="series-head-watched">
            <IconEye size={ICON_SIZE.xs} /> watched
            {target.watch_period ? ` · every ${target.watch_period}` : ""}
          </Text>
        )}
      </div>
      <h2 className="series-head-name">{name}</h2>
      <Group gap={4} wrap="nowrap" className="series-head-url">
        <Anchor href={target.url} target="_blank" rel="noreferrer" className="app-url">
          {target.url}
        </Anchor>
        <CopyIconButton value={target.url} label="Copy URL" />
      </Group>
      <Group gap="xs" wrap="wrap" className="series-head-actions">
        <Button
          size="xs"
          variant="default"
          leftSection={<IconPlay size={ICON_SIZE.sm} />}
          loading={poll.isPending}
          disabled={del.isPending}
          onClick={() => poll.mutate({ path: { target_id: target.id } })}
        >
          Poll now
        </Button>
        {lastJob !== null && (
          <Button
            size="xs"
            variant="subtle"
            rightSection={<IconArrowUpRight size={ICON_SIZE.xs} />}
            onClick={() => onOpenJob(lastJob)}
          >
            Job #{lastJob}
          </Button>
        )}
        <Button
          size="xs"
          variant="subtle"
          color="red"
          leftSection={<IconTrash size={ICON_SIZE.sm} />}
          disabled={poll.isPending || del.isPending}
          onClick={() => setConfirmingDelete(true)}
          className="series-head-remove"
        >
          Remove
        </Button>
      </Group>
      {confirmingDelete && (
        <InlineConfirm
          confirmLabel="Remove"
          message={
            <>
              Remove <strong>{name}</strong> from the library? Files on disk stay; you'll lose its
              tags, watch schedule and EPUB books.
            </>
          }
          loading={del.isPending}
          onCancel={() => setConfirmingDelete(false)}
          onConfirm={() =>
            del.mutate(
              { path: { target_id: target.id } },
              { onSettled: () => setConfirmingDelete(false) },
            )
          }
        />
      )}
    </div>
  );
}
