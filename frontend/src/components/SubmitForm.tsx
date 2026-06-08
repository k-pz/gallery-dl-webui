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
import { useEffect, useState } from "react";
import { createDownloadMutation, getConfigOptions } from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { DirectoryPicker } from "./DirectoryPicker";

export function SubmitForm({ onCreated }: { onCreated?: (id: number) => void } = {}) {
  const [url, setUrl] = useState("");
  const [outputDir, setOutputDir] = useState<string | null>(null);
  const [watched, setWatched] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [readingDirection, setReadingDirection] = useState<string>("ltr");
  const [readingDirectionTouched, setReadingDirectionTouched] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const invalidate = useDataInvalidators();
  const { data: config } = useQuery(getConfigOptions());

  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (!touched && config) {
      setOutputDir(config.postprocess_default_output_dir ?? null);
    }
  }, [config, touched]);

  useEffect(() => {
    if (!readingDirectionTouched && config?.default_reading_direction) {
      setReadingDirection(config.default_reading_direction);
    }
  }, [config, readingDirectionTouched]);

  const mutation = useMutation({
    ...createDownloadMutation(),
    onSuccess: (data) => {
      setUrl("");
      setWatched(false);
      setTags([]);
      setReadingDirectionTouched(false);
      setSubmitError(null);
      setTouched(false);
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
        output_dir: outputDir || null,
        watched,
        tags: tags.length > 0 ? tags : null,
        reading_direction: readingDirectionTouched ? readingDirection : null,
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
            style={{ flexGrow: 1, minWidth: 140 }}
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
          value={outputDir}
          onChange={(v) => {
            setTouched(true);
            setOutputDir(v);
          }}
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
            value={readingDirection}
            onChange={(v) => {
              if (!v) return;
              setReadingDirectionTouched(true);
              setReadingDirection(v);
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
