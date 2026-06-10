import {
  Anchor,
  Box,
  Button,
  Card,
  Collapse,
  Group,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  checkForUpdatesOptions,
  checkForUpdatesQueryKey,
  getUpdatePreviewRefOptions,
  getUpdatePreviewRefQueryKey,
  listMaintenanceJobsOptions,
  setUpdatePreviewRefMutation,
} from "../api/@tanstack/react-query.gen";
import type { ChangelogEntryOut, MaintenanceJob, UpdateCheckOut } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import { IconAlertTriangle, IconArrowUp, IconInfo } from "./Icons";
import { Pill } from "./Pill";

/**
 * Pulls the latest source from upstream, rebuilds, and restarts the LXC.
 *
 * The webapp itself is sandboxed and can't shell out to `/usr/local/bin/update`,
 * so it writes a sentinel file inside DATA_DIR; a pre-installed systemd path
 * unit watches for the file and fires the root-owned updater service. That
 * service ends by restarting this webapp — the user reloads when it returns.
 *
 * Two-stage confirm (no type-to-confirm): scheduling restarts the service, so
 * we want one extra click to prevent stray taps, but the action itself isn't
 * destructive enough to warrant the rebuild-library word-typing dance.
 *
 * Post-schedule state is *derived from the maintenance jobs list*, not flipped
 * to "queued" locally — otherwise an async failure (path unit dead, etc.) is
 * invisible: the API call succeeds (job created), the worker marks it failed,
 * and a local-only banner would still say "queued" forever.
 *
 * The "Track a specific ref" input under the banner persists a preview ref to
 * app_config; the worker writes it alongside the trigger file so the in-CT
 * updater pulls that branch / tag / SHA instead of `main`. Cleared input ==
 * default tracking.
 */
export function UpdateLxcCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: () => Promise<MaintenanceJob>;
}) {
  const qc = useQueryClient();
  const [armed, setArmed] = useState(false);
  // Id of the job we just scheduled — not "latest update_lxc job", which
  // could be a stale failure from a previous session and would otherwise
  // flash an error banner the moment the user clicks the button.
  const [trackedJobId, setTrackedJobId] = useState<number | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  // The backend caches results for 60 s; polling the UI every 5 min keeps the
  // status reasonably fresh without pinging GitHub on every render.
  const updateCheck = useQuery({
    ...checkForUpdatesOptions(),
    refetchInterval: 5 * 60 * 1000,
    staleTime: 60 * 1000,
  });

  // Shared cache with MaintenancePanel's identical query — react-query dedupes
  // so this is a free subscription, not an extra request.
  const jobs = useQuery({
    ...listMaintenanceJobsOptions(),
    refetchInterval: 3000,
  });
  const trackedJob =
    trackedJobId !== null ? (jobs.data ?? []).find((j) => j.id === trackedJobId) : undefined;

  const refresh = async () => {
    // Bypass the in-process backend cache, then write the fresh result onto
    // the key this card renders from — the forced variant lives under its
    // own query key (the options are part of the generated key), so an
    // invalidate alone would refetch the unforced key straight back out of
    // the backend's 60 s cache.
    try {
      const fresh = await qc.fetchQuery(checkForUpdatesOptions({ query: { force: true } }));
      qc.setQueryData(checkForUpdatesQueryKey(), fresh);
    } catch {
      // Network hiccup on a manual refresh — fall back to a plain refetch so
      // the user still gets whatever the backend can serve.
      qc.invalidateQueries({ queryKey: checkForUpdatesQueryKey() });
    }
  };

  const confirm = async () => {
    setScheduleError(null);
    setArmed(false);
    try {
      const created = await onSchedule();
      setTrackedJobId(created.id);
    } catch (err) {
      setScheduleError(extractErrorMessage(err));
    }
  };

  const retry = () => {
    setTrackedJobId(null);
    setScheduleError(null);
  };

  // Show the queued banner as soon as the schedule call resolves, even before
  // the jobs query catches up — otherwise there's a flicker back to the
  // button between mutateAsync resolving and the next refetch landing.
  const showStatus = trackedJobId !== null;

  return (
    <Card>
      <Stack gap="md">
        <Stack gap={4}>
          <span className="app-section-kicker">deployment</span>
          <Title order={3}>Update LXC from upstream</Title>
          <Text size="sm" c="dimmed">
            Pulls the latest <span className="code-chip">main</span> branch (or the preview ref set
            below), refreshes the backend/frontend toolchains, rebuilds the bundle, and restarts the
            service. The webapp will be unreachable for a few minutes during the install — reload
            this page once it comes back. Requires the LXC to have been provisioned by{" "}
            <span className="code-chip">scripts/proxmox-install.sh</span> (or refreshed by{" "}
            <span className="code-chip">/usr/local/bin/update</span>) so the helper systemd units
            are present.
          </Text>
        </Stack>
        <UpdateAvailabilityBanner check={updateCheck.data} onRefresh={refresh} />
        <PreviewRefControl
          defaultBranch={updateCheck.data?.branch ?? null}
          currentTrackedRef={updateCheck.data?.tracked_ref ?? null}
          availableTags={updateCheck.data?.available_tags ?? []}
        />
        {scheduleError ? (
          <Box className="app-alert">
            <IconAlertTriangle size={16} className="alert-icon" />
            <Stack gap={2}>
              <Text size="sm" fw={500}>
                Couldn't schedule the update
              </Text>
              <Text size="xs" c="dimmed">
                {scheduleError}
              </Text>
            </Stack>
          </Box>
        ) : null}
        {trackedJob?.status === "failed" ? (
          <Box className="app-alert">
            <IconAlertTriangle size={16} className="alert-icon" />
            <Stack gap={2} style={{ flex: 1 }}>
              <Text size="sm" fw={500}>
                Update failed
              </Text>
              <Text size="xs" c="dimmed">
                {trackedJob.error ?? "(no error message)"}
              </Text>
            </Stack>
            <Button variant="subtle" size="compact-xs" onClick={retry}>
              Try again
            </Button>
          </Box>
        ) : showStatus ? (
          <Box className="app-alert" data-tone="info">
            <IconInfo size={16} className="alert-icon" />
            <Stack gap={2}>
              <Text size="sm" fw={500}>
                Update queued
              </Text>
              <Text size="xs" c="dimmed">
                The service will restart automatically once the install completes. Reload this page
                in a few minutes; if it's still unreachable, check{" "}
                <span className="code-chip">journalctl -u gallery-dl-webui-update.service -f</span>{" "}
                from the LXC console.
              </Text>
            </Stack>
          </Box>
        ) : !armed ? (
          <Group wrap="wrap">
            <Button
              variant="light"
              leftSection={<IconArrowUp size={14} />}
              onClick={() => setArmed(true)}
              loading={scheduling}
              style={{ flexGrow: 1, minWidth: 140 }}
            >
              Update LXC…
            </Button>
          </Group>
        ) : (
          <Group gap="sm" wrap="wrap" align="flex-end">
            <Text size="sm" style={{ flex: 1, minWidth: 200 }}>
              Schedule an update? The service will restart at the end.
            </Text>
            <Button
              color="blue"
              leftSection={<IconArrowUp size={14} />}
              onClick={confirm}
              loading={scheduling}
              style={{ flexGrow: 1, minWidth: 160 }}
            >
              Yes, update now
            </Button>
            <Button
              variant="subtle"
              color="gray"
              onClick={() => setArmed(false)}
              style={{ flexGrow: 1, minWidth: 100 }}
            >
              Cancel
            </Button>
          </Group>
        )}
      </Stack>
    </Card>
  );
}

/** Always render tags with a leading `v` for display, no matter the source. */
function asVersionTag(value: string | null | undefined): string | null {
  if (!value) return null;
  return value.startsWith("v") ? value : `v${value}`;
}

function shortSha(sha: string | null | undefined): string | null {
  return sha ? sha.slice(0, 7) : null;
}

/**
 * Compact status block above the Update LXC button.
 *
 * Renders one of: "checking…", a version-based "Update available" panel with
 * an expandable changelog, a "Tracking preview ref" panel (commit list under
 * the same toggle), "Up to date", or a "couldn't check" line. The whole panel
 * stays low-key when nothing's interesting (up-to-date) and unfurls when the
 * user has a decision to make.
 */
function UpdateAvailabilityBanner({
  check,
  onRefresh,
}: {
  check: UpdateCheckOut | undefined;
  onRefresh: () => void;
}) {
  const [changelogOpen, setChangelogOpen] = useState(false);

  if (check === undefined) {
    return (
      <Text size="xs" c="dimmed">
        Checking for updates…
      </Text>
    );
  }

  const installedVersion = asVersionTag(check.current_version);
  const latestVersion = asVersionTag(check.latest_version);

  if (check.behind === true) {
    const isPreview = !check.tracked_ref_is_default;
    return (
      <Box className="app-alert" data-tone="info">
        <IconInfo size={16} className="alert-icon" />
        <Stack gap={6} style={{ flex: 1 }}>
          <Group gap="xs" wrap="wrap">
            <Text size="sm" fw={500}>
              Update available
            </Text>
            {isPreview ? (
              <Pill tone="info" noDot>
                preview · {check.tracked_ref}
              </Pill>
            ) : null}
          </Group>
          {!isPreview && latestVersion ? (
            <Text size="xs" c="dimmed">
              {installedVersion ?? shortSha(check.current_sha) ?? "unknown"} →{" "}
              <span className="code-chip">{latestVersion}</span>
            </Text>
          ) : (
            <Text size="xs" c="dimmed">
              Installed{" "}
              <span className="code-chip">
                {installedVersion ?? shortSha(check.current_sha) ?? "unknown"}
              </span>{" "}
              → ref <span className="code-chip">{check.tracked_ref ?? check.branch ?? "main"}</span>{" "}
              @ <span className="code-chip">{shortSha(check.latest_sha) ?? "?"}</span>
              {check.latest_message ? ` · ${check.latest_message}` : ""}
            </Text>
          )}
          <Group gap="xs">
            <Button
              variant="subtle"
              size="compact-xs"
              onClick={() => setChangelogOpen((v) => !v)}
              disabled={check.changelog.length === 0}
            >
              {changelogOpen ? "Hide changelog" : `Show changelog (${check.changelog.length})`}
            </Button>
          </Group>
          <Collapse expanded={changelogOpen}>
            <ChangelogList entries={check.changelog} isPreview={isPreview} />
          </Collapse>
        </Stack>
        <Button variant="subtle" size="compact-xs" onClick={onRefresh}>
          Refresh
        </Button>
      </Box>
    );
  }

  if (check.behind === false) {
    return (
      <Group gap="xs" wrap="nowrap">
        <Text size="xs" c="dimmed" style={{ flex: 1 }}>
          Up to date — installed{" "}
          <span className="code-chip">
            {installedVersion ?? shortSha(check.current_sha) ?? "unknown"}
          </span>{" "}
          on <span className="code-chip">{check.tracked_ref ?? check.branch ?? "main"}</span>
        </Text>
        <Button variant="subtle" size="compact-xs" onClick={onRefresh}>
          Refresh
        </Button>
      </Group>
    );
  }

  // behind === null → couldn't compare. The reason vocabulary mirrors what
  // backend/maintenance/update_check.py emits.
  return (
    <Group gap="xs" wrap="nowrap">
      <Text size="xs" c="dimmed" style={{ flex: 1 }}>
        Couldn't check for updates ({check.reason ?? "unknown"})
        {installedVersion || check.current_sha ? (
          <>
            {" "}
            — installed{" "}
            <span className="code-chip">
              {installedVersion ?? shortSha(check.current_sha) ?? "unknown"}
            </span>
          </>
        ) : null}
      </Text>
      <Button variant="subtle" size="compact-xs" onClick={onRefresh}>
        Retry
      </Button>
    </Group>
  );
}

/**
 * Vertical changelog list rendered inside the "Update available" panel.
 *
 * For default-branch tracking each entry is a GitHub Release: the body is the
 * markdown notes we render as plain text (no parsing — the source is
 * conventional-commit bullets which read fine as-is). For a preview ref the
 * list is one item per commit between the installed SHA and the ref's HEAD.
 */
function ChangelogList({
  entries,
  isPreview,
}: {
  entries: readonly ChangelogEntryOut[];
  isPreview: boolean;
}) {
  if (entries.length === 0) {
    return (
      <Text size="xs" c="dimmed">
        No changelog entries.
      </Text>
    );
  }
  // Cap the changelog at ~320px regardless of entry count; longer logs become
  // scrollable rather than pushing the Update button below the fold.
  return (
    <ScrollArea h={Math.min(320, Math.max(120, entries.length * 80))} type="auto">
      <Stack gap="sm">
        {entries.map((entry) => (
          <Box key={`${entry.ref}-${entry.title}`} className="changelog-entry">
            <Group gap="xs" wrap="wrap" align="baseline">
              <Text size="xs" fw={600}>
                {isPreview ? entry.title : entry.title}
              </Text>
              {entry.html_url ? (
                <Anchor href={entry.html_url} target="_blank" rel="noreferrer" size="xs" c="dimmed">
                  <span className="code-chip">{isPreview ? shortSha(entry.ref) : entry.ref}</span>
                </Anchor>
              ) : (
                <span className="code-chip">{isPreview ? shortSha(entry.ref) : entry.ref}</span>
              )}
              {entry.published_at ? (
                <Text size="xs" c="dimmed">
                  {new Date(entry.published_at).toLocaleDateString()}
                </Text>
              ) : null}
            </Group>
            {entry.body ? (
              <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>
                {entry.body.trim()}
              </Text>
            ) : null}
          </Box>
        ))}
      </Stack>
    </ScrollArea>
  );
}

/**
 * Inline "Track a specific ref" input.
 *
 * Persists the preview ref via PUT /api/maintenance/update-ref. Clearing the
 * field or "Reset to default" hits the same endpoint with null, which falls
 * back to whatever's in `.git/HEAD` (`main` in production).
 *
 * The saved-ref query is also what drives the input default: if the user
 * already has `develop` saved, the input pre-fills with it on reload. We
 * don't surface validation errors inline — the next update-check will report
 * `branch_not_on_remote` if the ref is wrong, which is more informative than
 * a per-keystroke check.
 *
 * `availableTags` (newest-first from GitHub) populates a Select beside the
 * text input — one click prefills the draft so the user doesn't have to type
 * the exact tag, while still leaving the free-text path open for branches /
 * SHAs / hand-typed tags.
 */
function PreviewRefControl({
  defaultBranch,
  currentTrackedRef,
  availableTags,
}: {
  defaultBranch: string | null;
  currentTrackedRef: string | null;
  availableTags: readonly string[];
}) {
  const qc = useQueryClient();
  const savedRef = useQuery(getUpdatePreviewRefOptions());
  const setMutation = useMutation({
    ...setUpdatePreviewRefMutation(),
    onSuccess: () => {
      // Hand the input back to the seeding effect only once the save landed;
      // doing it synchronously in save() re-seeded from the *stale* saved
      // ref until the invalidated refetch arrived, flickering the input.
      setHasTyped(false);
      qc.invalidateQueries({ queryKey: getUpdatePreviewRefQueryKey() });
      qc.invalidateQueries({ queryKey: checkForUpdatesQueryKey() });
    },
  });

  // Local input state is decoupled from the persisted value so the user can
  // type freely without each keystroke firing a request. We seed from the
  // saved ref on first arrival and on refresh, but don't fight the user once
  // they start typing (otherwise a refetch mid-type would clobber the input).
  const [draft, setDraft] = useState<string>("");
  const [hasTyped, setHasTyped] = useState(false);
  useEffect(() => {
    if (hasTyped) return;
    setDraft(savedRef.data?.ref ?? "");
  }, [savedRef.data, hasTyped]);

  const trimmed = draft.trim();
  const persistedRef = savedRef.data?.ref ?? null;
  const isDirty = trimmed !== (persistedRef ?? "");
  const fallback = defaultBranch ?? "main";

  const save = () => {
    const next = trimmed === "" || trimmed === fallback ? null : trimmed;
    setMutation.mutate({ body: { ref: next } });
  };

  const reset = () => {
    setDraft("");
    setMutation.mutate({ body: { ref: null } });
  };

  const errorMessage = setMutation.isError ? extractErrorMessage(setMutation.error) : null;

  // Picking a tag from the Select feeds the same draft pipeline as typing —
  // the user still sees what's about to be saved and can confirm with the
  // explicit Save button. `null` (cleared selection) leaves draft untouched
  // so accidentally re-clicking the picker doesn't wipe in-progress input.
  const tagOptions = availableTags.map((tag) => ({ value: tag, label: tag }));

  return (
    <Stack gap={6}>
      <Group gap="sm" align="flex-end" wrap="wrap">
        <TextInput
          label="Track ref"
          description={
            persistedRef
              ? `Currently tracking preview ref. Clear to reset to ${fallback}.`
              : `Tracking the default branch (${fallback}). Type a branch / tag / SHA to preview.`
          }
          placeholder={fallback}
          value={draft}
          onChange={(e) => {
            setHasTyped(true);
            setDraft(e.currentTarget.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && isDirty) {
              e.preventDefault();
              save();
            }
          }}
          style={{ flex: "1 1 220px", minWidth: 200 }}
          disabled={setMutation.isPending}
        />
        <Select
          label="Or pick a version tag"
          placeholder={tagOptions.length === 0 ? "no tags found" : "Select tag…"}
          data={tagOptions}
          value={tagOptions.some((o) => o.value === trimmed) ? trimmed : null}
          onChange={(value) => {
            if (value === null) return;
            setHasTyped(true);
            setDraft(value);
          }}
          searchable
          clearable={false}
          disabled={setMutation.isPending || tagOptions.length === 0}
          comboboxProps={{ withinPortal: true }}
          miw={150}
          style={{ flex: "1 1 180px" }}
        />
        <Button variant="light" onClick={save} loading={setMutation.isPending} disabled={!isDirty}>
          Save
        </Button>
        {persistedRef && (
          <Button variant="subtle" color="gray" onClick={reset} disabled={setMutation.isPending}>
            Reset to {fallback}
          </Button>
        )}
      </Group>
      {currentTrackedRef && persistedRef && currentTrackedRef !== persistedRef ? (
        <Text size="xs" c="dimmed">
          Saved <span className="code-chip">{persistedRef}</span>, currently checking{" "}
          <span className="code-chip">{currentTrackedRef}</span> — refresh to re-poll.
        </Text>
      ) : null}
      {errorMessage ? (
        <Text size="xs" c="red">
          {errorMessage}
        </Text>
      ) : null}
    </Stack>
  );
}
