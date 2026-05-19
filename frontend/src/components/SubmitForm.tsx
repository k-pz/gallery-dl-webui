import { Button, Card, Group, Stack, Text, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createDownloadMutation, getConfigOptions } from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { DirectoryPicker } from "./DirectoryPicker";

export function SubmitForm({ onCreated }: { onCreated?: (id: number) => void } = {}) {
  const [url, setUrl] = useState("");
  const [outputDir, setOutputDir] = useState<string | null>(null);
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

  const mutation = useMutation({
    ...createDownloadMutation(),
    onSuccess: (data) => {
      setUrl("");
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
      body: { url: trimmed, output_dir: outputDir || null },
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
        {submitError && (
          <Text size="sm" c="red">
            {submitError}
          </Text>
        )}
      </Stack>
    </Card>
  );
}
