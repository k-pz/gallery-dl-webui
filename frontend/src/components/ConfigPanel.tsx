import {
  Alert,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  getConfigOptions,
  getConfigQueryKey,
  putConfigMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";

export function ConfigPanel() {
  const { data, isLoading } = useQuery(getConfigOptions());
  const queryClient = useQueryClient();

  const [outputDir, setOutputDir] = useState("");
  const [deleteRaw, setDeleteRaw] = useState(true);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Reset form when the server-loaded config arrives or changes.
  useEffect(() => {
    if (data) {
      setOutputDir(data.postprocess_output_dir ?? "");
      setDeleteRaw(data.delete_raw_after_pack);
    }
  }, [data]);

  const mutation = useMutation({
    ...putConfigMutation(),
    onSuccess: () => {
      setSubmitError(null);
      setSavedAt(Date.now());
      queryClient.invalidateQueries({ queryKey: getConfigQueryKey() });
    },
    onError: (err) => {
      setSubmitError(extractErrorMessage(err));
    },
  });

  const dirty =
    data !== undefined &&
    ((outputDir.trim() || null) !== (data.postprocess_output_dir ?? null) ||
      deleteRaw !== data.delete_raw_after_pack);

  const save = () => {
    setSubmitError(null);
    setSavedAt(null);
    mutation.mutate({
      body: {
        postprocess_output_dir: outputDir.trim() || null,
        delete_raw_after_pack: deleteRaw,
      },
    });
  };

  if (isLoading || !data) {
    return (
      <Card withBorder shadow="sm" padding="lg">
        <Group>
          <Loader size="sm" />
          <Text>Loading config…</Text>
        </Group>
      </Card>
    );
  }

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Stack gap="md">
        <Title order={3}>Postprocessing</Title>
        <Text size="sm" c="dimmed">
          When set, finished manga downloads are packed into Komga-compatible CBZ archives at{" "}
          <code>&lt;dir&gt;/&lt;Series&gt;/&lt;Series&gt; - cNNN.cbz</code>.
        </Text>
        <TextInput
          label="Output directory"
          placeholder="/mnt/manga"
          description="Absolute path. Must be writable by the service user (see EXTRA_RW_PATHS in scripts/proxmox-install.sh for paths outside WEBUI_DATA_DIR)."
          value={outputDir}
          onChange={(e) => setOutputDir(e.currentTarget.value)}
          disabled={mutation.isPending}
        />
        <Switch
          label="Delete raw images after packing"
          description="Remove the downloaded source directory once a chapter's CBZ is written."
          checked={deleteRaw}
          onChange={(e) => setDeleteRaw(e.currentTarget.checked)}
          disabled={mutation.isPending}
        />
        <Group>
          <Button onClick={save} loading={mutation.isPending} disabled={!dirty}>
            Save
          </Button>
          {savedAt !== null && !dirty && !submitError && (
            <Text size="sm" c="green">
              Saved.
            </Text>
          )}
        </Group>
        {submitError && (
          <Alert color="red" variant="light">
            {submitError}
          </Alert>
        )}
      </Stack>
    </Card>
  );
}
