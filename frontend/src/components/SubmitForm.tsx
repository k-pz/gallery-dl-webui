import {
  Button,
  Card,
  Checkbox,
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

  // Seed the output-dir field with the default whenever the config arrives or changes,
  // but only while the user hasn't picked something themselves.
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (!touched && config) {
      setOutputDir(config.postprocess_default_output_dir ?? null);
    }
  }, [config, touched]);

  // Sync the reading-direction default from server config until the user
  // picks one themselves (mirrors the output-dir seeding above).
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
        title: "Download queued",
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
      setSubmitError("url is required");
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
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Title order={3}>Add a download</Title>
        <Group align="flex-end" gap="sm" wrap="nowrap">
          <TextInput
            style={{ flex: 1 }}
            label="Gallery URL"
            placeholder="https://mangadex.org/title/..."
            value={url}
            onChange={(e) => setUrl(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                submit();
              }
            }}
            disabled={mutation.isPending}
          />
          <Button onClick={submit} loading={mutation.isPending}>
            Download
          </Button>
        </Group>
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
        <TagsInput
          label="Tags"
          placeholder="Enter to add — e.g. action, romance"
          description="Applied to series.json + ComicInfo. Existing tags are replaced on every submit."
          value={tags}
          onChange={setTags}
          disabled={mutation.isPending}
          clearable
        />
        <Select
          label="Reading direction"
          description="Overrides the default for this series. RTL becomes ComicInfo Manga=YesAndRightToLeft."
          value={readingDirection}
          onChange={(v) => {
            if (!v) return;
            setReadingDirectionTouched(true);
            setReadingDirection(v);
          }}
          data={READING_DIRECTION_OPTIONS}
          disabled={mutation.isPending}
          maw={260}
          allowDeselect={false}
        />
        <Checkbox
          label="Watch"
          checked={watched}
          onChange={(e) => setWatched(e.currentTarget.checked)}
          disabled={mutation.isPending}
        />
        {submitError && (
          <Text size="sm" c="red">
            {submitError}
          </Text>
        )}
      </Stack>
    </Card>
  );
}
