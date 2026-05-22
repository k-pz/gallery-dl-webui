import {
  ActionIcon,
  Box,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Modal,
  PasswordInput,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  cancelMaintenanceJobMutation,
  checkForUpdatesOptions,
  checkForUpdatesQueryKey,
  listMaintenanceJobsOptions,
  listMaintenanceJobsQueryKey,
  scheduleMaintenanceJobMutation,
} from "../api/@tanstack/react-query.gen";
import type { UpdateCheckOut } from "../api/types.gen";
import { extractErrorMessage } from "../lib/apiError";
import { usePagination } from "../lib/pagination";
import { statusTone } from "../lib/status";
import { EmptyState } from "./EmptyState";
import {
  IconAlertTriangle,
  IconArrowUp,
  IconClock,
  IconFileText,
  IconInfo,
  IconRefresh,
  IconUpload,
} from "./Icons";
import { ListPagination } from "./ListPagination";
import { MaintenanceLog } from "./MaintenanceLog";
import { Pill } from "./Pill";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

// The literal the user must type to arm the rebuild. Kept short, lowercase
// only — anything longer becomes annoying to type for a deliberately
// frequent-enough op.
const REBUILD_CONFIRM_WORD = "rebuild";

const KIND_LABEL: Record<string, string> = {
  rename_chapters: "Rename chapters",
  regenerate_series_metadata: "Regenerate series metadata",
  rebuild_library: "Rebuild library",
  push_komga_series_status: "Push series status to Komga",
  update_lxc: "Update LXC from upstream",
};

export function MaintenancePanel() {
  const qc = useQueryClient();
  const jobs = useQuery({
    ...listMaintenanceJobsOptions(),
    refetchInterval: 3000,
  });
  const schedule = useMutation({
    ...scheduleMaintenanceJobMutation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: listMaintenanceJobsQueryKey() }),
  });
  const cancel = useMutation({
    ...cancelMaintenanceJobMutation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: listMaintenanceJobsQueryKey() }),
  });

  const jobList = jobs.data ?? [];
  const pagination = usePagination(jobList, "maintenance");
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  const [userPicked, setUserPicked] = useState(false);
  useEffect(() => {
    if (userPicked) return;
    if (jobList.length === 0) {
      setSelectedJobId(null);
      return;
    }
    setSelectedJobId(jobList[0].id);
  }, [jobList, userPicked]);

  const scheduleError = schedule.isError ? extractErrorMessage(schedule.error) : null;

  return (
    <Stack gap="lg">
      <Card>
        <Stack gap="md">
          <Stack gap={4}>
            <span className="app-section-kicker">postprocessing</span>
            <Title order={3}>Schedule maintenance</Title>
            <Text size="sm" c="dimmed">
              One-off jobs that fan out over the library: rename CBZs, refresh series metadata. Safe
              and idempotent.
            </Text>
          </Stack>
          <Group wrap="wrap">
            <Button
              variant="light"
              leftSection={<IconRefresh size={14} />}
              onClick={() => schedule.mutate({ body: { kind: "rename_chapters" } })}
              loading={schedule.isPending}
            >
              Schedule chapter rename
            </Button>
            <Button
              variant="light"
              leftSection={<IconFileText size={14} />}
              onClick={() => schedule.mutate({ body: { kind: "regenerate_series_metadata" } })}
              loading={schedule.isPending}
            >
              Regenerate series metadata
            </Button>
          </Group>
          {scheduleError && (
            <Box className="app-alert">
              <Text size="sm">{scheduleError}</Text>
            </Box>
          )}
        </Stack>
      </Card>

      <PushKomgaStatusCard
        scheduling={schedule.isPending}
        onSchedule={(params) =>
          schedule.mutate({ body: { kind: "push_komga_series_status", params } })
        }
      />

      <UpdateLxcCard
        scheduling={schedule.isPending}
        onSchedule={() => schedule.mutate({ body: { kind: "update_lxc" } })}
      />

      <RebuildLibraryCard
        scheduling={schedule.isPending}
        onSchedule={() => schedule.mutate({ body: { kind: "rebuild_library" } })}
      />

      <Card>
        <Stack gap="md">
          <Stack gap={4}>
            <span className="app-section-kicker">history</span>
            <Group justify="space-between" align="baseline">
              <Title order={4}>Maintenance jobs</Title>
              {jobs.isLoading && <Loader size="xs" />}
            </Group>
          </Stack>
          {jobs.isError && (
            <Box className="app-alert">
              <IconAlertTriangle size={16} className="alert-icon" />
              <Text size="sm">{extractErrorMessage(jobs.error)}</Text>
            </Box>
          )}
          {cancel.isError && (
            <Box className="app-alert">
              <IconAlertTriangle size={16} className="alert-icon" />
              <Text size="sm">{extractErrorMessage(cancel.error)}</Text>
            </Box>
          )}
          {jobList.length === 0 && !jobs.isLoading && (
            <EmptyState
              icon={<IconClock size={20} />}
              title="No maintenance jobs yet"
              body="Scheduled background jobs (rename, regenerate, rebuild) and their results show up here."
            />
          )}
          {jobList.length > 0 && (
            <Box
              style={{
                border: "1px solid var(--app-border-subtle)",
                borderRadius: "var(--mantine-radius-md)",
                overflow: "hidden",
              }}
            >
              <Table
                verticalSpacing="sm"
                highlightOnHover
                stickyHeader
                className="maint-jobs-table"
              >
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th style={{ width: 64 }}>ID</Table.Th>
                    <Table.Th>Job</Table.Th>
                    <Table.Th style={{ width: 140 }}>Status</Table.Th>
                    <Table.Th>Result</Table.Th>
                    <Table.Th style={{ width: 56 }} aria-label="Actions" />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {pagination.pageItems.map((job) => {
                    const cancellable = !TERMINAL_STATUSES.has(job.status);
                    const isSelected = selectedJobId === job.id;
                    return (
                      <Table.Tr
                        key={job.id}
                        onClick={() => {
                          setSelectedJobId(job.id);
                          setUserPicked(true);
                        }}
                        style={{
                          cursor: "pointer",
                          backgroundColor: isSelected ? "var(--app-surface-muted)" : undefined,
                        }}
                        aria-label={`Select maintenance job ${job.id}`}
                      >
                        <Table.Td>
                          <Text size="sm" ff="monospace" c="dimmed">
                            {job.id}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={2}>
                            <Text size="sm" fw={500}>
                              {KIND_LABEL[job.kind] ?? job.kind}
                            </Text>
                            <Text size="xs" c="dimmed" ff="monospace">
                              {job.kind}
                            </Text>
                          </Stack>
                        </Table.Td>
                        <Table.Td>
                          <Pill tone={statusTone(job.status)}>{job.status}</Pill>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs" ff="monospace" c="dimmed" className="maint-result">
                            {job.result ? JSON.stringify(job.result) : (job.error ?? "—")}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          {cancellable && (
                            <Tooltip label="Cancel job" withArrow>
                              <ActionIcon
                                variant="subtle"
                                color="red"
                                aria-label={`Cancel maintenance job ${job.id}`}
                                loading={
                                  cancel.isPending && cancel.variables?.path?.job_id === job.id
                                }
                                onClick={(e) => {
                                  e.stopPropagation();
                                  cancel.mutate({ path: { job_id: job.id } });
                                }}
                              >
                                ✕
                              </ActionIcon>
                            </Tooltip>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Box>
          )}
          <ListPagination
            page={pagination.page}
            setPage={pagination.setPage}
            totalPages={pagination.totalPages}
            start={pagination.start}
            end={pagination.end}
            total={pagination.total}
            ariaLabel="Maintenance jobs pagination"
          />
          {selectedJobId !== null && jobList.length > 0 && (
            <>
              <Divider />
              <MaintenanceLog
                jobId={selectedJobId}
                startedAt={jobList.find((j) => j.id === selectedJobId)?.started_at}
              />
            </>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}

/**
 * Destructive op lives on its own card with a red border and a type-to-confirm
 * field. The button doesn't accept the click until the user has typed exactly
 * `rebuild`, so a stray cursor never wipes anyone's library.
 */
function RebuildLibraryCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const [typed, setTyped] = useState("");
  const matches = useMemo(() => typed.trim().toLowerCase() === REBUILD_CONFIRM_WORD, [typed]);

  const reset = () => {
    setArmed(false);
    setTyped("");
  };

  return (
    <Card className="maintenance-destructive">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
            <span className="app-section-kicker">destructive</span>
            <Title order={3} style={{ color: "var(--tone-error)" }}>
              Rebuild library
            </Title>
            <Text size="sm" c="dimmed">
              Wipes every downloaded chapter, the gallery-dl archive, the raw downloads dir, and
              everything under the postprocess root (excluded directory names are spared). Every
              watched series is re-queued from scratch. There's no undo. Plan to be offline for
              several hours.
            </Text>
          </Stack>
          <IconAlertTriangle size={20} style={{ color: "var(--tone-error)", flexShrink: 0 }} />
        </Group>
        {!armed ? (
          <Group>
            <Button
              variant="outline"
              color="red"
              leftSection={<IconAlertTriangle size={14} />}
              onClick={() => setArmed(true)}
              loading={scheduling}
            >
              Rebuild library…
            </Button>
          </Group>
        ) : (
          <Stack gap="sm">
            <Text size="sm">
              To confirm, type <span className="code-chip">{REBUILD_CONFIRM_WORD}</span> below. The
              next run is scheduled immediately and cannot be reverted.
            </Text>
            <Group gap="sm" wrap="wrap" align="flex-end">
              <TextInput
                aria-label="Type rebuild to confirm"
                placeholder={REBUILD_CONFIRM_WORD}
                value={typed}
                onChange={(e) => setTyped(e.currentTarget.value)}
                style={{ flex: 1, minWidth: 200, maxWidth: 240 }}
                styles={{ input: { fontFamily: "var(--app-mono)" } }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && matches) {
                    onSchedule();
                    reset();
                  }
                }}
                autoFocus
              />
              <Button
                color="red"
                leftSection={<IconAlertTriangle size={14} />}
                disabled={!matches}
                loading={scheduling}
                onClick={() => {
                  onSchedule();
                  reset();
                }}
              >
                Rebuild library
              </Button>
              <Button variant="subtle" color="gray" onClick={reset} disabled={scheduling}>
                Cancel
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}

/**
 * Push the local `series_status` of every target into the matching Komga series.
 *
 * Credentials are collected in a modal on every run and sent inline with the
 * schedule request — they're held in worker memory just long enough to run
 * the job and then dropped. Nothing is persisted server-side beyond the job
 * row itself (which never sees the credentials).
 */
function PushKomgaStatusCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: (params: { base_url: string; username: string; password: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const reset = () => {
    setBaseUrl("");
    setUsername("");
    setPassword("");
  };

  const close = () => {
    setOpen(false);
    // Drop the password from React state the moment the modal closes so it
    // doesn't sit around in memory between runs.
    reset();
  };

  const trimmedUrl = baseUrl.trim();
  const urlValid = /^https?:\/\//i.test(trimmedUrl);
  const canSubmit = urlValid && username.trim().length > 0 && password.length > 0 && !scheduling;

  const submit = () => {
    if (!canSubmit) return;
    onSchedule({
      base_url: trimmedUrl.replace(/\/+$/, ""),
      username: username.trim(),
      password,
    });
    close();
  };

  return (
    <Card>
      <Stack gap="md">
        <Stack gap={4}>
          <span className="app-section-kicker">komga sync</span>
          <Title order={3}>Push series status to Komga</Title>
          <Text size="sm" c="dimmed">
            Pushes every watched series' local status (Ongoing / Ended / Hiatus / Abandoned) to a
            matching Komga series, found by exact name match. Credentials are required on every run
            and are never stored on disk.
          </Text>
        </Stack>
        <Group>
          <Button
            variant="light"
            leftSection={<IconUpload size={14} />}
            onClick={() => setOpen(true)}
            loading={scheduling}
          >
            Push status to Komga…
          </Button>
        </Group>
      </Stack>

      <Modal opened={open} onClose={close} title="Push series status to Komga" centered size="md">
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Credentials are used once for this job and never written to the database. Re-enter them
            for each push.
          </Text>
          <TextInput
            label="Komga base URL"
            placeholder="https://komga.example.com"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.currentTarget.value)}
            error={baseUrl.length > 0 && !urlValid ? "Must start with http:// or https://" : null}
            autoFocus
            required
          />
          <TextInput
            label="Username (or email)"
            value={username}
            onChange={(e) => setUsername(e.currentTarget.value)}
            autoComplete="off"
            required
          />
          <PasswordInput
            label="Password"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            autoComplete="off"
            required
            onKeyDown={(e) => {
              if (e.key === "Enter" && canSubmit) submit();
            }}
          />
          <Group justify="flex-end" gap="sm">
            <Button variant="subtle" color="gray" onClick={close} disabled={scheduling}>
              Cancel
            </Button>
            <Button
              leftSection={<IconUpload size={14} />}
              onClick={submit}
              disabled={!canSubmit}
              loading={scheduling}
            >
              Push status
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

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
 */
function UpdateLxcCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: () => void;
}) {
  const qc = useQueryClient();
  const [armed, setArmed] = useState(false);
  const [scheduled, setScheduled] = useState(false);

  // The backend caches results for 60 s; polling the UI every 5 min keeps the
  // status reasonably fresh without pinging GitHub on every render.
  const updateCheck = useQuery({
    ...checkForUpdatesOptions(),
    refetchInterval: 5 * 60 * 1000,
    staleTime: 60 * 1000,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: checkForUpdatesQueryKey() });
    // Bypass the in-process backend cache too, so the user can force-pull on
    // demand right after pushing a commit upstream.
    qc.fetchQuery({ ...checkForUpdatesOptions({ query: { force: true } }) });
  };

  const confirm = () => {
    onSchedule();
    setArmed(false);
    setScheduled(true);
  };

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
        {scheduled ? (
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
