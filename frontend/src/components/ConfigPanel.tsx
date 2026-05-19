import {
  Alert,
  Button,
  Card,
  Group,
  Loader,
  type MantineColorScheme,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  useMantineColorScheme,
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
  const { colorScheme, setColorScheme } = useMantineColorScheme();

  const [root, setRoot] = useState("");
  const [defaultDir, setDefaultDir] = useState("");
  const [deleteRaw, setDeleteRaw] = useState(true);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (data) {
      setRoot(data.postprocess_root ?? "");
      setDefaultDir(data.postprocess_default_output_dir ?? "");
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
    ((root.trim() || null) !== (data.postprocess_root ?? null) ||
      (defaultDir.trim() || null) !== (data.postprocess_default_output_dir ?? null) ||
      deleteRaw !== data.delete_raw_after_pack);

  const save = () => {
    setSubmitError(null);
    setSavedAt(null);
    mutation.mutate({
      body: {
        postprocess_root: root.trim() || null,
        postprocess_default_output_dir: defaultDir.trim() || null,
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
        <Title order={3}>Appearance</Title>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Theme
          </Text>
          <Text size="xs" c="dimmed">
            Auto follows your system preference.
          </Text>
          <SegmentedControl
            aria-label="Theme"
            value={colorScheme}
            onChange={(value) => setColorScheme(value as MantineColorScheme)}
            data={[
              { label: "Auto", value: "auto" },
              { label: "Light", value: "light" },
              { label: "Dark", value: "dark" },
            ]}
          />
        </Stack>
        <Title order={3}>Postprocessing</Title>
        <Text size="sm" c="dimmed">
          When a root is set, finished downloads are packed into Komga-compatible CBZs at{" "}
          <code>&lt;output-dir&gt;/&lt;Series&gt;/&lt;Series&gt; - cNNN.cbz</code>. Every
          per-download output directory must live under the root.
        </Text>
        <TextInput
          label="Root"
          placeholder="/mnt/nas/Media"
          description="Absolute path. The hard upper bound for every output dir. Created if missing; must be writable."
          value={root}
          onChange={(e) => setRoot(e.currentTarget.value)}
          disabled={mutation.isPending}
        />
        <TextInput
          label="Default output directory"
          placeholder="/mnt/nas/Media/manga"
          description="Used when a download is submitted without an explicit output dir. Must be under the root."
          value={defaultDir}
          onChange={(e) => setDefaultDir(e.currentTarget.value)}
          disabled={mutation.isPending || !root.trim()}
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
        {data.postprocess_known_output_dirs.length > 0 && (
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Remembered output directories
            </Text>
            <Stack gap={2}>
              {data.postprocess_known_output_dirs.map((dir) => (
                <Text key={dir} size="xs" c="dimmed" ff="monospace">
                  {dir}
                </Text>
              ))}
            </Stack>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
