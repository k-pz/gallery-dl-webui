import { Box, Button, Card, Divider, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  cancelMaintenanceJobMutation,
  listMaintenanceJobsOptions,
  listMaintenanceJobsQueryKey,
  scheduleMaintenanceJobMutation,
} from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { usePagination } from "../lib/pagination";
import { EmptyState } from "./EmptyState";
import {
  ICON_SIZE,
  IconAlertTriangle,
  IconClock,
  IconEyeOff,
  IconFileText,
  IconRefresh,
} from "./Icons";
import { KomgaSyncCard } from "./KomgaSyncCard";
import { ListPagination } from "./ListPagination";
import { MaintenanceJobsTable } from "./MaintenanceJobsTable";
import { MaintenanceLog } from "./MaintenanceLog";
import { RebuildLibraryCard } from "./RebuildLibraryCard";
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
  // One shared mutation backs eight unrelated buttons; gate each button's
  // spinner on the kind it actually submits so clicking one doesn't put
  // the whole tab into a loading state.
  const schedulingKind = schedule.isPending ? schedule.variables?.body?.kind : undefined;

  return (
    <Stack gap="lg">
      <Card>
        <Stack gap="md">
          <Stack gap={4}>
            <span className="app-section-kicker">postprocessing</span>
            <Title order={3}>Schedule maintenance</Title>
            <Text size="sm" c="dimmed">
              One-off jobs that sweep the whole library: rename CBZs, refresh series metadata. Safe
              to run repeatedly (idempotent) — re-running won't double up or undo earlier runs.
            </Text>
          </Stack>
          <Group wrap="wrap">
            <Button
              variant="light"
              leftSection={<IconRefresh size={ICON_SIZE.sm} />}
              onClick={() => schedule.mutate({ body: { kind: "rename_chapters" } })}
              loading={schedulingKind === "rename_chapters"}
            >
              Schedule chapter rename
            </Button>
            <Button
              variant="light"
              leftSection={<IconFileText size={ICON_SIZE.sm} />}
              onClick={() => schedule.mutate({ body: { kind: "refresh_series_metadata" } })}
              loading={schedulingKind === "refresh_series_metadata"}
            >
              Refresh series metadata
            </Button>
            <Button
              variant="light"
              leftSection={<IconFileText size={ICON_SIZE.sm} />}
              onClick={() => schedule.mutate({ body: { kind: "regenerate_series_metadata" } })}
              loading={schedulingKind === "regenerate_series_metadata"}
            >
              Regenerate series metadata
            </Button>
            <Button
              variant="light"
              leftSection={<IconEyeOff size={ICON_SIZE.sm} />}
              onClick={() => schedule.mutate({ body: { kind: "unwatch_ended_series" } })}
              loading={schedulingKind === "unwatch_ended_series"}
            >
              Unwatch ended series
            </Button>
          </Group>
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
              body="Jobs you schedule above — and what they did — show up here."
            />
          )}
          {jobList.length > 0 && (
            <MaintenanceJobsTable
              jobs={pagination.pageItems}
              selectedJobId={selectedJobId}
              onSelect={(id) => {
                setSelectedJobId(id);
                setUserPicked(true);
              }}
              cancellingJobId={cancel.isPending ? (cancel.variables?.path?.job_id ?? null) : null}
              onCancel={(id) => cancel.mutate({ path: { job_id: id } })}
            />
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
