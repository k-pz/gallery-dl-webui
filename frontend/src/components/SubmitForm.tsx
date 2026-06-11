import {
  Button,
  Card,
  Checkbox,
  Divider,
  Group,
  Select,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { createDownloadMutation, getConfigOptions } from "../api/@tanstack/react-query.gen";
import { useServerSeededState } from "../hooks/useServerSeededState";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { DirectoryPicker } from "./DirectoryPicker";

export function SubmitForm({ onCreated }: { onCreated?: (id: number) => void } = {}) {
  const [url, setUrl] = useState("");
  const [watched, setWatched] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
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
      setSubmitError(null);
      outputDir.markClean();
      onCreated?.(data.id);
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
      notifications.show({
        title: "Submission failed",
        message: msg,
        color: "red",
      });
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
    <Card>
      <Stack gap="lg">
        <Stack gap={4}>
          <span className="app-section-kicker">new job</span>
          <Title order={3}>Add a series</Title>
        </Stack>
        <Group align="flex-end" gap="sm" wrap="wrap">
          <TextInput
            style={{ flex: 1, minWidth: 220 }}
            label="Gallery URL"
            placeholder="https://mangadex.org/title/…"
            value={url}
            onChange={(e) => setUrl(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                submit();
              }
            }}
            disabled={mutation.isPending}
            size="md"
          />
          <Button
            onClick={submit}
            loading={mutation.isPending}
            size="md"
            // Grows to fill its own wrapped line on phones, but capped so it
            // doesn't balloon to half the card next to the URL on desktop.
            style={{ flexGrow: 1, minWidth: 140, maxWidth: 260 }}
          >
            Download
          </Button>
        </Group>
        {submitError && (
          <Text size="sm" c="red">
            {submitError}
          </Text>
        )}
        <Divider />
        <Stack gap={2}>
          <span className="app-section-kicker">destination &amp; metadata</span>
          <Text size="xs" c="dimmed">
            Optional — leave alone to use the configured defaults.
          </Text>
        </Stack>
        <DirectoryPicker
          label="Output directory"
          placeholder={hasRoot ? "/mnt/nas/Media/manga" : "Set a root in Config first"}
          description={
            hasRoot
              ? `Must be under root: ${config?.postprocess_root}. Use + to create a new folder.`
              : "Postprocessing disabled until a root is configured."
          }
          value={outputDir.value}
          onChange={outputDir.setValue}
          enabled={hasRoot}
          disabled={mutation.isPending}
          extraOption={config?.postprocess_default_output_dir ?? null}
        />
        <Group align="flex-start" gap="md" grow wrap="wrap">
          <TagsInput
            label="Tags"
            placeholder="Enter to add — e.g. action, romance"
            description="Written into this series' metadata (series.json + ComicInfo.xml). Submitting again replaces this series' tags only — other series are untouched."
            value={tags}
            onChange={setTags}
            disabled={mutation.isPending}
            clearable
          />
          <Select
            label="Reading direction"
            description="Right-to-left tells the reader to page backwards (written into ComicInfo.xml as Manga=YesAndRightToLeft)."
            value={readingDirection.value}
            onChange={(v) => {
              if (!v) return;
              readingDirection.setValue(v);
            }}
            data={READING_DIRECTION_OPTIONS}
            disabled={mutation.isPending}
            allowDeselect={false}
          />
        </Group>
        <Checkbox
          label="Watch"
          description="Check for new chapters on a repeating schedule (the default cadence set in Config)."
          checked={watched}
          onChange={(e) => setWatched(e.currentTarget.checked)}
          disabled={mutation.isPending}
        />
      </Stack>
    </Card>
  );
}
