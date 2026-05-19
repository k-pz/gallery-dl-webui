import { Autocomplete, Button, Card, Group, Stack, Text, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  createDownloadMutation,
  getConfigOptions,
  getConfigQueryKey,
  listDownloadsQueryKey,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";

export function SubmitForm({ onCreated }: { onCreated: (id: number) => void }) {
  const [url, setUrl] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { data: config } = useQuery(getConfigOptions());

  // Seed the output-dir field with the default whenever the config arrives or changes,
  // but only while the user hasn't typed something themselves.
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (!touched && config) {
      setOutputDir(config.postprocess_default_output_dir ?? "");
    }
  }, [config, touched]);

  const suggestions = useMemo(() => {
    if (!config) return [] as string[];
    const seen = new Set<string>();
    const out: string[] = [];
    const push = (value: string | null | undefined) => {
      if (!value) return;
      if (seen.has(value)) return;
      seen.add(value);
      out.push(value);
    };
    push(config.postprocess_default_output_dir);
    for (const dir of config.postprocess_known_output_dirs) push(dir);
    return out;
  }, [config]);

  const mutation = useMutation({
    ...createDownloadMutation(),
    onSuccess: (data) => {
      setUrl("");
      setSubmitError(null);
      setTouched(false);
      onCreated(data.id);
      notifications.show({
        title: "Download queued",
        message: `Job #${data.id} added to the queue.`,
        color: "green",
      });
      queryClient.invalidateQueries({ queryKey: listDownloadsQueryKey() });
      queryClient.invalidateQueries({ queryKey: getConfigQueryKey() });
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
    const dir = outputDir.trim();
    mutation.mutate({
      body: { url: trimmed, output_dir: dir || null },
    });
  };

  const hasRoot = Boolean(config?.postprocess_root);

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="sm">
        <Title order={3}>New download</Title>
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
        <Autocomplete
          label="Output directory"
          placeholder={hasRoot ? "/mnt/nas/Media/manga" : "Set a root in Config first"}
          description={
            hasRoot
              ? `Must be under root: ${config?.postprocess_root}. New paths are created on submit.`
              : "Postprocessing disabled until a root is configured."
          }
          data={suggestions}
          value={outputDir}
          onChange={(value) => {
            setTouched(true);
            setOutputDir(value);
          }}
          disabled={mutation.isPending || !hasRoot}
          limit={20}
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
