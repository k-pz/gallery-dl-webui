import { Box, Button, Card, Loader, Stack, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import {
  cancelMaintenanceJobMutation,
  listMaintenanceJobsOptions,
  listMaintenanceJobsQueryKey,
  scheduleMaintenanceJobMutation,
} from "../api/@tanstack/react-query.gen";
import { useScreenLayout } from "../hooks/useScreenLayout";
import { extractErrorMessage } from "../lib/apiError";
import { EmptyState } from "./EmptyState";
import {
  ICON_SIZE,
  IconAlertTriangle,
  IconClock,
  IconEyeOff,
  IconFileText,
  IconLibrary,
  IconRefresh,
} from "./Icons";
import { KomgaSyncCard } from "./KomgaSyncCard";
import { MaintenanceJobsTable } from "./MaintenanceJobsTable";
import { MaintenanceLog } from "./MaintenanceLog";
import { RebuildLibraryCard } from "./RebuildLibraryCard";
import { Pane, Screen } from "./Screen";
import { UpdateLxcCard } from "./UpdateLxcCard";

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

  const layout = useScreenLayout();
  const jobList = jobs.data ?? [];
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
  // One shared mutation backs eight unrelated buttons; gate each button's
  // spinner on the kind it actually submits so clicking one doesn't put
  // the whole tab into a loading state.
  const schedulingKind = schedule.isPending ? schedule.variables?.body?.kind : undefined;

  const selectedJob = jobList.find((j) => j.id === selectedJobId);
  const scheduleButton = (kind: string, label: string, icon: ReactNode) => (
    <Button
      variant="light"
      leftSection={icon}
      onClick={() => schedule.mutate({ body: { kind } })}
      loading={schedulingKind === kind}
    >
      {label}
    </Button>
  );

  return (
    <Screen name="maintenance" layout={layout}>
      <Pane label="Maintenance actions" className="maint-actions">
        <Card>
          <Stack gap="md">
            <Stack gap={4}>
              <span className="app-section-kicker">postprocessing</span>
              <Title order={3}>Schedule maintenance</Title>
              <Text size="sm" c="dimmed">
                One-off jobs that sweep the whole library: rename CBZs, refresh series metadata,
                fill chapter volumes. Safe to run repeatedly (idempotent) — re-running won't double
                up or undo earlier runs.
              </Text>
            </Stack>
            <div className="maint-action-grid">
              {scheduleButton(
                "rename_chapters",
                "Schedule chapter rename",
                <IconRefresh size={ICON_SIZE.sm} />,
              )}
              {scheduleButton(
                "refresh_series_metadata",
                "Refresh series metadata",
                <IconFileText size={ICON_SIZE.sm} />,
              )}
              {scheduleButton(
                "regenerate_series_metadata",
                "Regenerate series metadata",
                <IconFileText size={ICON_SIZE.sm} />,
              )}
              {scheduleButton(
                "fill_mangadex_volumes",
                "Fill volumes from MangaDex",
                <IconLibrary size={ICON_SIZE.sm} />,
              )}
              {scheduleButton(
                "unwatch_ended_series",
                "Unwatch ended series",
                <IconEyeOff size={ICON_SIZE.sm} />,
              )}
            </div>
            {scheduleError && (
              <Box className="app-alert">
                <Text size="sm">{scheduleError}</Text>
              </Box>
            )}
          </Stack>
        </Card>

        <KomgaSyncCard
          schedulingStatus={schedulingKind === "push_komga_series_status"}
          onScheduleStatus={() => schedule.mutate({ body: { kind: "push_komga_series_status" } })}
          schedulingMetadata={schedulingKind === "sync_komga_metadata"}
          onScheduleMetadata={() => schedule.mutate({ body: { kind: "sync_komga_metadata" } })}
        />

        <UpdateLxcCard
          scheduling={schedulingKind === "update_lxc"}
          onSchedule={() => schedule.mutateAsync({ body: { kind: "update_lxc" } })}
        />

        <RebuildLibraryCard
          scheduling={schedulingKind === "rebuild_library"}
          onSchedule={() => schedule.mutate({ body: { kind: "rebuild_library" } })}
        />
      </Pane>

      <Pane
        label="Maintenance jobs"
        className="maint-history"
        kicker="history"
        title="Maintenance jobs"
        actions={jobs.isLoading ? <Loader size="xs" /> : undefined}
      >
        <Stack gap="md" p="md">
          {jobs.isError && (
            <Box className="app-alert">
              <IconAlertTriangle size={ICON_SIZE.md} className="alert-icon" />
              <Text size="sm">{extractErrorMessage(jobs.error)}</Text>
            </Box>
          )}
          {cancel.isError && (
            <Box className="app-alert">
              <IconAlertTriangle size={ICON_SIZE.md} className="alert-icon" />
              <Text size="sm">{extractErrorMessage(cancel.error)}</Text>
            </Box>
          )}
          {jobList.length === 0 && !jobs.isLoading && (
            <EmptyState
              icon={<IconClock size={ICON_SIZE.xl} />}
              title="No maintenance jobs yet"
              body="Jobs you schedule — and what they did — show up here."
            />
          )}
          {jobList.length > 0 && (
            <MaintenanceJobsTable
              jobs={jobList}
              selectedJobId={selectedJobId}
              onSelect={(id) => {
                setSelectedJobId(id);
                setUserPicked(true);
              }}
              cancellingJobId={cancel.isPending ? (cancel.variables?.path?.job_id ?? null) : null}
              onCancel={(id) => cancel.mutate({ path: { job_id: id } })}
            />
          )}
        </Stack>
      </Pane>

      <Pane
        label="Job log"
        className={selectedJob ? "maint-log-pane" : "maint-log-pane pane-empty"}
      >
        {selectedJob ? (
          <MaintenanceLog
            jobId={selectedJob.id}
            startedAt={selectedJob.started_at}
            fill={layout !== "stack"}
          />
        ) : (
          <EmptyState compact title="No job selected" body="Pick a job to follow its log." />
        )}
      </Pane>
    </Screen>
  );
}
