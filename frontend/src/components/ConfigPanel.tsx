import {
  Alert,
  Box,
  Button,
  Code,
  Group,
  Loader,
  type MantineColorScheme,
  NumberInput,
  PasswordInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  useMantineColorScheme,
} from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { getConfigOptions, putConfigMutation } from "../api/@tanstack/react-query.gen";
import { useScreenLayout } from "../hooks/useScreenLayout";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";
import { READING_DIRECTION_OPTIONS } from "../lib/readingDirection";
import { AppVersion } from "./AppVersion";
import { DirectoryPicker } from "./DirectoryPicker";
import { FormSection } from "./FormSection";
import { LibraryBackup } from "./LibraryBackup";
import { Pane, Screen } from "./Screen";

/** Sections of the form, in order, for the section nav. */
const CONFIG_SECTIONS = [
  { id: "theme", kicker: "appearance", label: "Theme" },
  { id: "packing", kicker: "postprocessing", label: "CBZ packing" },
  { id: "polling", kicker: "watching", label: "Polling cadence" },
  { id: "parallelism", kicker: "concurrency", label: "Parallelism" },
  { id: "komga", kicker: "komga sync", label: "Komga" },
  { id: "epub", kicker: "export", label: "EPUB export" },
  { id: "dirs", kicker: "cache", label: "Output directories" },
  { id: "backup", kicker: "library backup", label: "Export / import" },
] as const;

const sectionDomId = (id: string) => `config-${id}`;

function ConfigSection({ id, children }: { id: string; children: ReactNode }) {
  return (
    <section id={sectionDomId(id)} data-section={id} className="cfg-section">
      {children}
    </section>
  );
}

export function ConfigPanel() {
  const { data, isLoading } = useQuery(getConfigOptions());
  const invalidate = useDataInvalidators();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const layout = useScreenLayout();
  const formRef = useRef<HTMLDivElement | null>(null);
  const [activeSection, setActiveSection] = useState<string>(CONFIG_SECTIONS[0].id);
  // Highlight the section nearest the top of the form pane in the nav.
  // Skipped where IntersectionObserver is missing (tests, old browsers).
  useEffect(() => {
    const rootEl = layout === "stack" ? null : formRef.current;
    if (typeof IntersectionObserver === "undefined" || !data) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        const id = top?.target.getAttribute("data-section");
        if (id) setActiveSection(id);
      },
      { root: rootEl, rootMargin: "0px 0px -70% 0px" },
    );
    for (const el of document.querySelectorAll("[data-section]")) observer.observe(el);
    return () => observer.disconnect();
  }, [layout, data]);

  const [root, setRoot] = useState("");
  const [defaultDir, setDefaultDir] = useState<string | null>(null);
  const [defaultPeriod, setDefaultPeriod] = useState("");
  const [chapterTemplate, setChapterTemplate] = useState("");
  const [deleteRaw, setDeleteRaw] = useState(true);
  const [readingDirection, setReadingDirection] = useState("ltr");
  const [excludedDirsRaw, setExcludedDirsRaw] = useState("");
  const [maxPostprocess, setMaxPostprocess] = useState<number>(3);
  const [komgaBaseUrl, setKomgaBaseUrl] = useState("");
  const [komgaApiKey, setKomgaApiKey] = useState("");
  const [epubExportDir, setEpubExportDir] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Re-seed the form whenever fresh config arrives — but never while the
  // user has unsaved edits. The config query is invalidated by unrelated
  // actions (another tab saving, a download submit), and re-seeding then
  // would silently wipe in-progress input. `touchedRef` flips on the first
  // user edit and resets once a save lands (or the seed runs).
  const touchedRef = useRef(false);
  useEffect(() => {
    if (data && !touchedRef.current) {
      setRoot(data.postprocess_root ?? "");
      setDefaultDir(data.postprocess_default_output_dir ?? null);
      setDefaultPeriod(data.default_watch_period ?? "");
      setChapterTemplate(data.chapter_naming_template ?? "");
      setDeleteRaw(data.delete_raw_after_pack);
      setReadingDirection(data.default_reading_direction ?? "ltr");
      setExcludedDirsRaw((data.postprocess_excluded_dir_names ?? []).join(", "));
      setMaxPostprocess(data.max_parallel_postprocess ?? 3);
      setKomgaBaseUrl(data.komga_base_url ?? "");
      setKomgaApiKey(data.komga_api_key ?? "");
      setEpubExportDir(data.epub_export_dir ?? "");
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
      touchedRef.current = false;
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
      maxPostprocess !== (data.max_parallel_postprocess ?? 3) ||
      (komgaBaseUrl.trim() || null) !== (data.komga_base_url ?? null) ||
      (komgaApiKey.trim() || null) !== (data.komga_api_key ?? null) ||
      (epubExportDir.trim() || null) !== (data.epub_export_dir ?? null) ||
      excludedDirty);

  /** Wrap a state setter so any user edit marks the form as touched. */
  function touch<T>(setter: (value: T) => void): (value: T) => void {
    return (value: T) => {
      touchedRef.current = true;
      setter(value);
    };
  }

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
        max_parallel_postprocess: maxPostprocess,
        komga_base_url: komgaBaseUrl.trim() || null,
        komga_api_key: komgaApiKey.trim() || null,
        epub_export_dir: epubExportDir.trim() || null,
      },
    });
  };

  if (isLoading || !data) {
    return (
      <Screen name="config" layout={layout}>
        <Pane label="Configuration" className="pane-empty">
          <Group>
            <Loader size="sm" />
            <Text>Loading configuration…</Text>
          </Group>
        </Pane>
      </Screen>
    );
  }

  const hasRoot = Boolean(root.trim());
  const sections = CONFIG_SECTIONS.filter(
    (sec) => sec.id !== "dirs" || data.postprocess_known_output_dirs.length > 0,
  );
  const goTo = (id: string) => {
    setActiveSection(id);
    document.getElementById(sectionDomId(id))?.scrollIntoView({ block: "start" });
  };

  const saveBar = (
    <>
      {submitError && (
        <Alert color="red" variant="light" className="cfg-save-error">
          {submitError}
        </Alert>
      )}
      <Text size="sm" c="dimmed" className="cfg-save-status">
        {dirty
          ? "Edited — save to apply"
          : savedAt !== null && !submitError
            ? "Saved."
            : "No changes"}
      </Text>
      {(dirty || mutation.isPending) && (
        <Button onClick={save} loading={mutation.isPending} disabled={!dirty}>
          Save changes
        </Button>
      )}
    </>
  );

  return (
    <Screen name="config" layout={layout}>
      <nav className="pane cfg-nav" aria-label="Config sections">
        <ul className="cfg-nav-list">
          {sections.map((sec) => (
            <li key={sec.id}>
              <a
                href={`#${sectionDomId(sec.id)}`}
                className="cfg-nav-link"
                aria-current={activeSection === sec.id ? "true" : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  goTo(sec.id);
                }}
              >
                <span className="cfg-nav-kicker">{sec.kicker}</span>
                {sec.label}
              </a>
            </li>
          ))}
        </ul>
        <div className="app-footnote cfg-nav-foot">
          gallery-dl · webui · <AppVersion />
        </div>
      </nav>

      <Pane label="Configuration" className="cfg-form" footer={saveBar} bodyRef={formRef}>
        <ConfigSection id="theme">
          <FormSection
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
              maw={420}
            />
          </FormSection>
        </ConfigSection>

        <ConfigSection id="packing">
          <FormSection
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
              onChange={(e) => touch(setRoot)(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
            <DirectoryPicker
              label="Default output directory"
              placeholder="/mnt/nas/Media/manga"
              description="Used when a download is submitted without an explicit output dir. Must be under the root."
              value={defaultDir}
              onChange={touch(setDefaultDir)}
              enabled={hasRoot}
              disabled={mutation.isPending}
            />
            <Switch
              label="Delete raw images after packing"
              description="Remove the downloaded source directory once a chapter's CBZ is written."
              checked={deleteRaw}
              onChange={(e) => touch(setDeleteRaw)(e.currentTarget.checked)}
              disabled={mutation.isPending}
            />
            <TextInput
              label="Chapter naming template"
              description={
                <>
                  Names each CBZ from a Jinja2 template. Example:{" "}
                  <Code>{"{{ series }} - {{ chapter }} - {{ title }}"}</Code>. Variables: series,
                  manga, chapter, chapter_number, title, volume, lang, author, date.
                </>
              }
              value={chapterTemplate}
              onChange={(e) => touch(setChapterTemplate)(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
            <Select
              label="Default reading direction"
              description="Applied to series.json + ComicInfo.xml when a download doesn't override it. Komga only reads LTR vs RTL from CBZ metadata; vertical/webtoon are passed through series.json."
              value={readingDirection}
              onChange={(v) => v && touch(setReadingDirection)(v)}
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
              onChange={(e) => touch(setExcludedDirsRaw)(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
          </FormSection>
        </ConfigSection>

        <ConfigSection id="polling">
          <FormSection
            kicker="watching"
            title="Polling cadence"
            description="Per-target overrides win; otherwise watched targets re-poll on this cadence."
          >
            <TextInput
              label="Default poll period"
              placeholder="1d"
              description="Format: 30m, 2h, 1d, 1w (combinable, e.g. 1d12h)."
              value={defaultPeriod}
              onChange={(e) => touch(setDefaultPeriod)(e.currentTarget.value)}
              disabled={mutation.isPending}
              maw={260}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
          </FormSection>
        </ConfigSection>

        <ConfigSection id="parallelism">
          <FormSection
            kicker="concurrency"
            title="Parallelism"
            description="Restart the service to apply a change here. A higher value packs more CBZs at once within a single job — faster, but with heavier disk I/O."
          >
            <NumberInput
              label="Max parallel postprocess"
              description="CBZ packing threads per job."
              value={maxPostprocess}
              onChange={(v) => touch(setMaxPostprocess)(typeof v === "number" ? v : maxPostprocess)}
              min={1}
              max={16}
              disabled={mutation.isPending}
              w={240}
            />
          </FormSection>
        </ConfigSection>

        <ConfigSection id="komga">
          <FormSection
            kicker="komga sync"
            title="Komga"
            description={
              <>
                Used by the <Code>Push series status to Komga</Code> maintenance job. Generate an
                API key in Komga under Account Settings → API keys.
              </>
            }
          >
            <TextInput
              label="Komga base URL"
              placeholder="https://komga.example.com"
              description="Trailing slash is stripped. Must start with http:// or https://."
              value={komgaBaseUrl}
              onChange={(e) => touch(setKomgaBaseUrl)(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
            <PasswordInput
              label="Komga API key"
              description="Sent as the X-API-Key header. Stored in the local app database; never sent anywhere besides your Komga instance."
              value={komgaApiKey}
              onChange={(e) => touch(setKomgaApiKey)(e.currentTarget.value)}
              disabled={mutation.isPending}
              autoComplete="off"
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
          </FormSection>
        </ConfigSection>

        <ConfigSection id="epub">
          <FormSection
            kicker="export"
            title="EPUB export"
            description={
              <>
                Books exported from a series in the Library are written to{" "}
                <Code>&lt;export-dir&gt;/&lt;Series&gt;/&lt;Series&gt; - Vol. NN.epub</Code>.
              </>
            }
          >
            <TextInput
              label="EPUB export directory"
              placeholder={data.epub_export_dir_default}
              description="Leave empty to use the default shown. Doesn't need to be under the root. Created if missing; must be writable."
              value={epubExportDir}
              onChange={(e) => touch(setEpubExportDir)(e.currentTarget.value)}
              disabled={mutation.isPending}
              styles={{ input: { fontFamily: "var(--app-mono)" } }}
            />
          </FormSection>
        </ConfigSection>

        {data.postprocess_known_output_dirs.length > 0 && (
          <ConfigSection id="dirs">
            <FormSection kicker="cache" title="Remembered output directories">
              <Box className="cfg-known-dirs">
                <Stack gap={4}>
                  {data.postprocess_known_output_dirs.map((dir) => (
                    <Text key={dir} size="xs" c="dimmed" ff="monospace">
                      {dir}
                    </Text>
                  ))}
                </Stack>
              </Box>
            </FormSection>
          </ConfigSection>
        )}

        <ConfigSection id="backup">
          <FormSection
            kicker="library backup"
            title="Export / import"
            description="Save and restore the library as a YAML file (URL, name, output dir, watch state). Not part of the form above: it applies at once."
          >
            <LibraryBackup />
          </FormSection>
        </ConfigSection>
      </Pane>
    </Screen>
  );
}
