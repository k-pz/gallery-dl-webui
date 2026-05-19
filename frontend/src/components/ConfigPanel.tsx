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
import { DirectoryPicker } from "./DirectoryPicker";

export function ConfigPanel() {
  const { data, isLoading } = useQuery(getConfigOptions());
  const queryClient = useQueryClient();
  const { colorScheme, setColorScheme } = useMantineColorScheme();

  const [root, setRoot] = useState("");
  const [defaultDir, setDefaultDir] = useState<string | null>(null);
  const [defaultPeriod, setDefaultPeriod] = useState("");
  const [deleteRaw, setDeleteRaw] = useState(true);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (data) {
      setRoot(data.postprocess_root ?? "");
      setDefaultDir(data.postprocess_default_output_dir ?? null);
      setDefaultPeriod(data.default_watch_period ?? "");
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
      (defaultDir || null) !== (data.postprocess_default_output_dir ?? null) ||
      (defaultPeriod.trim() || null) !== (data.default_watch_period ?? null) ||
      deleteRaw !== data.delete_raw_after_pack);

  const save = () => {
    setSubmitError(null);
    setSavedAt(null);
    mutation.mutate({
      body: {
        postprocess_root: root.trim() || null,
        postprocess_default_output_dir: defaultDir || null,
        delete_raw_after_pack: deleteRaw,
        default_watch_period: defaultPeriod.trim() || null,
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

  const hasRoot = Boolean(root.trim());

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
        <DirectoryPicker
          label="Default output directory"
          placeholder="/mnt/nas/Media/manga"
          description="Used when a download is submitted without an explicit output dir. Must be under the root."
          value={defaultDir}
          onChange={setDefaultDir}
          enabled={hasRoot}
          disabled={mutation.isPending}
        />
        <Switch
          label="Delete raw images after packing"
          description="Remove the downloaded source directory once a chapter's CBZ is written."
          checked={deleteRaw}
          onChange={(e) => setDeleteRaw(e.currentTarget.checked)}
          disabled={mutation.isPending}
        />
        <Title order={3}>Watching</Title>
        <TextInput
          label="Default poll period"
          placeholder="1d"
          description="Per-target overrides win; otherwise watched targets re-poll on this cadence. Format: 30m, 2h, 1d, 1w (combinable, e.g. 1d12h)."
          value={defaultPeriod}
          onChange={(e) => setDefaultPeriod(e.currentTarget.value)}
          disabled={mutation.isPending}
          maw={260}
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
