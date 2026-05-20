import {
  Alert,
  Box,
  Button,
  Card,
  Code,
  Divider,
  FileButton,
  Group,
  List,
  Loader,
  type MantineColorScheme,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  useMantineColorScheme,
} from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { getConfigOptions, putConfigMutation } from "../api/@tanstack/react-query.gen";
import type { LibraryImportResult } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { exportLibrary, importLibrary } from "../lib/libraryBackup";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { DirectoryPicker } from "./DirectoryPicker";

function Section({
  kicker,
  title,
  description,
  children,
}: {
  kicker: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Stack gap="md">
      <Stack gap={4}>
        <span className="app-section-kicker">{kicker}</span>
        <Title order={4}>{title}</Title>
        {description && (
          <Text size="sm" c="dimmed">
            {description}
          </Text>
        )}
      </Stack>
      {children}
    </Stack>
  );
}

export function ConfigPanel() {
  const { data, isLoading } = useQuery(getConfigOptions());
  const invalidate = useDataInvalidators();
  const { colorScheme, setColorScheme } = useMantineColorScheme();

  const [root, setRoot] = useState("");
  const [defaultDir, setDefaultDir] = useState<string | null>(null);
  const [defaultPeriod, setDefaultPeriod] = useState("");
  const [chapterTemplate, setChapterTemplate] = useState("");
  const [deleteRaw, setDeleteRaw] = useState(true);
  const [readingDirection, setReadingDirection] = useState("ltr");
  const [excludedDirsRaw, setExcludedDirsRaw] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (data) {
      setRoot(data.postprocess_root ?? "");
      setDefaultDir(data.postprocess_default_output_dir ?? null);
      setDefaultPeriod(data.default_watch_period ?? "");
      setChapterTemplate(data.chapter_naming_template ?? "");
      setDeleteRaw(data.delete_raw_after_pack);
      setReadingDirection(data.default_reading_direction ?? "ltr");
      setExcludedDirsRaw((data.postprocess_excluded_dir_names ?? []).join(", "));
    }
  }, [data]);

  const parsedExcluded = excludedDirsRaw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const existingExcluded = data?.postprocess_excluded_dir_names ?? [];
  const excludedDirty =
    parsedExcluded.length !== existingExcluded.length ||
    parsedExcluded.some((name, idx) => name !== existingExcluded[idx]);

  const mutation = useMutation({
    ...putConfigMutation(),
    onSuccess: () => {
      setSubmitError(null);
      setSavedAt(Date.now());
      invalidate.config();
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
      chapterTemplate.trim() !== (data.chapter_naming_template ?? "") ||
      deleteRaw !== data.delete_raw_after_pack ||
      readingDirection !== (data.default_reading_direction ?? "ltr") ||
      excludedDirty);

  const save = () => {
    setSubmitError(null);
    setSavedAt(null);
    mutation.mutate({
      body: {
        postprocess_root: root.trim() || null,
        postprocess_default_output_dir: defaultDir || null,
        delete_raw_after_pack: deleteRaw,
        default_watch_period: defaultPeriod.trim() || null,
        chapter_naming_template: chapterTemplate.trim() || null,
        default_reading_direction: readingDirection,
        postprocess_excluded_dir_names: parsedExcluded,
      },
    });
  };

  if (isLoading || !data) {
    return (
      <Card>
        <Group>
          <Loader size="sm" />
          <Text>Loading config…</Text>
        </Group>
      </Card>
    );
  }

  const hasRoot = Boolean(root.trim());

  return (
    <Stack gap="lg">
      <Card>
        <Section
          kicker="appearance"
          title="Theme"
          description="Auto follows your system preference."
        >
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
        </Section>
      </Card>

      <Card>
        <Stack gap="xl">
          <Section
            kicker="postprocessing"
            title="CBZ packing"
            description={
              <>
                When a root is set, finished downloads are packed into Komga-compatible CBZs at{" "}
                <Code>&lt;output-dir&gt;/&lt;Series&gt;/&lt;chapter-name&gt;.cbz</Code>. Every
                per-download output directory must live under the root.
              </>
            }
          >
            <TextInput
              label="Root"
              placeholder="/mnt/nas/Media"
              description="Absolute path. The hard upper bound for every output dir. Created if missing; must be writable."
              value={root}
              onChange={(e) => setRoot(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
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
            <TextInput
              label="Chapter naming template"
              description="Jinja2 template variables: series, manga, chapter, chapter_number, title, volume, lang, author, date."
              value={chapterTemplate}
              onChange={(e) => setChapterTemplate(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
            <Select
              label="Default reading direction"
              description="Applied to series.json + ComicInfo.xml when a download doesn't override it. Komga only reads LTR vs RTL from CBZ metadata; vertical/webtoon are passed through series.json."
              value={readingDirection}
              onChange={(v) => v && setReadingDirection(v)}
              data={READING_DIRECTION_OPTIONS}
              disabled={mutation.isPending}
              maw={280}
              allowDeselect={false}
            />
            <TextInput
              label="Excluded directory names"
              description="Comma-separated. Directories whose name matches (anywhere in the path) are skipped by the output-dir picker and by maintenance scans. Useful for NAS trash like #recycle or @eaDir."
              placeholder="#recycle, @eaDir, .Trash"
              value={excludedDirsRaw}
              onChange={(e) => setExcludedDirsRaw(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
          </Section>

          <Divider />

          <Section
            kicker="watching"
            title="Polling cadence"
            description="Per-target overrides win; otherwise watched targets re-poll on this cadence."
          >
            <TextInput
              label="Default poll period"
              placeholder="1d"
              description="Format: 30m, 2h, 1d, 1w (combinable, e.g. 1d12h)."
              value={defaultPeriod}
              onChange={(e) => setDefaultPeriod(e.currentTarget.value)}
              disabled={mutation.isPending}
              maw={260}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
          </Section>

          {(dirty || mutation.isPending || savedAt !== null || submitError) && (
            <Stack gap="sm">
              <Group>
                {(dirty || mutation.isPending) && (
                  <Button onClick={save} loading={mutation.isPending} disabled={!dirty}>
                    Save changes
                  </Button>
                )}
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
          )}

          {data.postprocess_known_output_dirs.length > 0 && (
            <>
              <Divider />
              <Section kicker="cache" title="Remembered output directories">
                <Box
                  style={{
                    background: "var(--app-surface-muted)",
                    border: "1px solid var(--app-border-subtle)",
                    borderRadius: "var(--mantine-radius-md)",
                    padding: "0.75rem 1rem",
                  }}
                >
                  <Stack gap={4}>
                    {data.postprocess_known_output_dirs.map((dir) => (
                      <Text key={dir} size="xs" c="dimmed" ff="monospace">
                        {dir}
                      </Text>
                    ))}
                  </Stack>
                </Box>
              </Section>
            </>
          )}
        </Stack>
      </Card>

      <Card>
        <Section
          kicker="library backup"
          title="Export / import"
          description="Save and restore the library as a YAML file (URL, name, output dir, watch state)."
        >
          <LibraryBackup />
        </Section>
      </Card>
    </Stack>
  );
}

function LibraryBackup() {
  const invalidate = useDataInvalidators();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<LibraryImportResult | null>(null);

  const doExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await exportLibrary();
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  const doImport = async (file: File | null) => {
    if (!file) return;
    setImportBusy(true);
    setImportError(null);
    setImportResult(null);
    try {
      const result = await importLibrary(file);
      setImportResult(result);
      invalidate.targets();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err));
    } finally {
      setImportBusy(false);
    }
  };

  return (
    <Stack gap="md">
      <Group>
        <Button variant="light" onClick={doExport} loading={exporting}>
          Export library
        </Button>
        <FileButton onChange={doImport} accept=".yaml,.yml,application/yaml,text/yaml,text/plain">
          {(props) => (
            <Button variant="light" loading={importBusy} {...props}>
              Import library…
            </Button>
          )}
        </FileButton>
      </Group>
      {exportError && (
        <Alert color="red" variant="light">
          Export failed: {exportError}
        </Alert>
      )}
      {importError && (
        <Alert color="red" variant="light">
          Import failed: {importError}
        </Alert>
      )}
      {importResult && (
        <Alert
          color={importResult.errors.length > 0 ? "yellow" : "green"}
          variant="light"
          title={`Imported ${importResult.imported}, updated ${importResult.updated}`}
        >
          {importResult.errors.length === 0 ? (
            <Text size="sm">Done.</Text>
          ) : (
            <Stack gap={4}>
              <Text size="sm">{importResult.errors.length} entries had problems:</Text>
              <List size="sm" withPadding>
                {importResult.errors.map((e) => (
                  <List.Item key={e}>{e}</List.Item>
                ))}
              </List>
            </Stack>
          )}
        </Alert>
      )}
    </Stack>
  );
}
