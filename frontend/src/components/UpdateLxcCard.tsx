import { Box, Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  checkForUpdatesOptions,
  checkForUpdatesQueryKey,
  listMaintenanceJobsOptions,
} from "../api/@tanstack/react-query.gen";
import type { MaintenanceJob, UpdateCheckOut } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import { IconAlertTriangle, IconArrowUp, IconInfo } from "./Icons";

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

  const refresh = () => {
    qc.invalidateQueries({ queryKey: checkForUpdatesQueryKey() });
    // Bypass the in-process backend cache too, so the user can force-pull on
    // demand right after pushing a commit upstream.
    qc.fetchQuery({ ...checkForUpdatesOptions({ query: { force: true } }) });
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
            Pulls the latest <span className="code-chip">main</span> branch, refreshes the
            backend/frontend toolchains, rebuilds the bundle, and restarts the service. The webapp
            will be unreachable for a few minutes during the install — reload this page once it
            comes back. Requires the LXC to have been provisioned by{" "}
            <span className="code-chip">scripts/proxmox-install.sh</span> (or refreshed by{" "}
            <span className="code-chip">/usr/local/bin/update</span>) so the helper systemd units
            are present.
          </Text>
        </Stack>
        <UpdateAvailabilityBanner check={updateCheck.data} onRefresh={refresh} />
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
          <Group>
            <Button
              variant="light"
              leftSection={<IconArrowUp size={14} />}
              onClick={() => setArmed(true)}
              loading={scheduling}
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
            >
              Yes, update now
            </Button>
            <Button variant="subtle" color="gray" onClick={() => setArmed(false)}>
              Cancel
            </Button>
          </Group>
        )}
      </Stack>
    </Card>
  );
}

/**
 * Compact status line above the Update LXC button.
 *
 * Renders one of: "checking…", "update available <short sha> · <subject>",
 * "up to date", or a "couldn't check" line with the reason. Inline so the
 * card stays low-key when nothing is interesting.
 */
function UpdateAvailabilityBanner({
  check,
  onRefresh,
}: {
  check: UpdateCheckOut | undefined;
  onRefresh: () => void;
}) {
  if (check === undefined) {
    return (
      <Text size="xs" c="dimmed">
        Checking for updates…
      </Text>
    );
  }

  const shortSha = (sha: string | null) => (sha ? sha.slice(0, 7) : null);

  if (check.behind === true) {
    return (
      <Box className="app-alert" data-tone="info">
        <IconInfo size={16} className="alert-icon" />
        <Stack gap={2} style={{ flex: 1 }}>
          <Text size="sm" fw={500}>
            Update available — {shortSha(check.latest_sha)}
          </Text>
          {check.latest_message && (
            <Text size="xs" c="dimmed">
              {check.latest_message}
            </Text>
          )}
          <Text size="xs" c="dimmed">
            Installed: <span className="code-chip">{shortSha(check.current_sha)}</span> on{" "}
            <span className="code-chip">{check.branch}</span>
          </Text>
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
          Up to date — installed <span className="code-chip">{shortSha(check.current_sha)}</span> on{" "}
          <span className="code-chip">{check.branch}</span>
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
        {check.current_sha && (
          <>
            {" "}
            — installed <span className="code-chip">{shortSha(check.current_sha)}</span>
          </>
        )}
      </Text>
      <Button variant="subtle" size="compact-xs" onClick={onRefresh}>
        Retry
      </Button>
    </Group>
  );
}
