import {
  ActionIcon,
  Button,
  Checkbox,
  Collapse,
  Select,
  TagsInput,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { createDownloadMutation, getConfigOptions } from "../api/@tanstack/react-query.gen";
import { useServerSeededState } from "../hooks/useServerSeededState";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { DirectoryPicker } from "./DirectoryPicker";
import { ICON_SIZE, IconSliders } from "./Icons";

/**
 * One-line "add a series" form at the top of the library list. The URL and
 * the Add button are always visible; the optional destination and metadata
 * fields fold away behind the options button so they don't push the list
 * down.
 */
export function AddSeriesBar() {
  const [url, setUrl] = useState("");
  const [watched, setWatched] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const optionsId = useId();
  const invalidate = useDataInvalidators();
  const { data: config } = useQuery(getConfigOptions());

  // Both pre-fill from the configured defaults (which may arrive after first
  // render) but must not clobber a user's explicit pick on a config refetch.
  const outputDir = useServerSeededState(config?.postprocess_default_output_dir ?? null);
  const readingDirection = useServerSeededState(config?.default_reading_direction ?? "ltr");

  const mutation = useMutation({
    ...createDownloadMutation(),
    onSuccess: (data) => {
      setUrl("");
      setWatched(false);
      setTags([]);
      readingDirection.markClean();
      outputDir.markClean();
      setSubmitError(null);
      notifications.show({
        title: "Job queued",
        message: `Job #${data.id} added to the queue.`,
        color: "green",
      });
      invalidate.downloads();
      invalidate.targets();
      invalidate.config();
    },
    onError: (err) => {
      const msg = extractErrorMessage(err);
      setSubmitError(msg);
      notifications.show({ title: "Submission failed", message: msg, color: "red" });
    },
  });

  const submit = () => {
    const trimmed = url.trim();
    if (!trimmed) {
      setSubmitError("Enter a gallery URL.");
      return;
    }
    mutation.mutate({
      body: {
        url: trimmed,
        output_dir: outputDir.value || null,
        watched,
        tags: tags.length > 0 ? tags : null,
        reading_direction: readingDirection.dirty ? readingDirection.value : null,
      },
    });
  };

  const hasRoot = Boolean(config?.postprocess_root);

  return (
    <form
      className="lib-add"
      aria-label="Add a series"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="lib-add-row">
        <TextInput
          className="lib-add-url"
          aria-label="Gallery URL"
          placeholder="Paste a gallery URL to add a series"
          value={url}
          onChange={(e) => setUrl(e.currentTarget.value)}
          disabled={mutation.isPending}
          error={submitError ?? undefined}
        />
        <Tooltip label={optionsOpen ? "Hide download options" : "Download options"} withArrow>
          <ActionIcon
            variant={optionsOpen ? "light" : "default"}
            size={36}
            aria-label="Download options"
            aria-expanded={optionsOpen}
            aria-controls={optionsId}
            onClick={() => setOptionsOpen((o) => !o)}
          >
            <IconSliders size={ICON_SIZE.md} />
          </ActionIcon>
        </Tooltip>
        <Button type="submit" loading={mutation.isPending} className="lib-add-submit">
          Add
        </Button>
      </div>
      <Collapse expanded={optionsOpen}>
        <div className="lib-add-options" id={optionsId}>
          <DirectoryPicker
            label="Output directory"
            placeholder={hasRoot ? "/mnt/nas/Media/manga" : "Set a root in Config first"}
            description={
              hasRoot
                ? `Under ${config?.postprocess_root}. Use + to create a folder.`
                : "Packing to CBZ is off until a root is set in Config."
            }
            value={outputDir.value}
            onChange={outputDir.setValue}
            enabled={hasRoot}
            disabled={mutation.isPending}
            extraOption={config?.postprocess_default_output_dir ?? null}
          />
          <div className="lib-add-pair">
            <TagsInput
              label="Tags"
              placeholder="Enter to add"
              description="Replaces this series' tags in series.json and ComicInfo.xml."
              value={tags}
              onChange={setTags}
              disabled={mutation.isPending}
              clearable
            />
            <Select
              label="Reading direction"
              description="Right to left pages backwards in readers."
              value={readingDirection.value}
              onChange={(v) => {
                if (v) readingDirection.setValue(v);
              }}
              data={READING_DIRECTION_OPTIONS}
              disabled={mutation.isPending}
              allowDeselect={false}
              comboboxProps={{ withinPortal: true }}
            />
          </div>
          <Checkbox
            label="Watch for new chapters"
            description="Polls on the default schedule set in Config."
            checked={watched}
            onChange={(e) => setWatched(e.currentTarget.checked)}
            disabled={mutation.isPending}
          />
        </div>
      </Collapse>
    </form>
  );
}
