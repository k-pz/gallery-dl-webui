import { useScreenLayout } from "../hooks/useScreenLayout";
import { ActiveJobCard } from "./ActiveJobCard";
import { EmptyState } from "./EmptyState";
import { RecentList } from "./RecentList";
import { RunningJobsPanel } from "./RunningJobsPanel";
import { Pane, Screen, StackedView } from "./Screen";

/**
 * The Jobs tab as one screen: the job lists beside the selected job, each
 * pane scrolling on its own.
 *
 *   ultra  running and queued | all jobs | job detail
 *   split  running, queued and all jobs in one pane | job detail
 *   stack  the lists flow with the page; a job the user picks opens full
 *          screen with a back button (the auto-selected running job does
 *          not, so the list stays reachable)
 */
export function JobsView({
  selectedId,
  isManualSelection,
  onSelect,
}: {
  selectedId: number | null;
  /** The selection came from the user (a pick or a deep link), not the auto-open. */
  isManualSelection: boolean;
  onSelect: (id: number | null) => void;
}) {
  const layout = useScreenLayout();
  const close = () => onSelect(null);

  if (layout === "stack") {
    return (
      <Screen name="jobs" layout="stack">
        <Pane label="Jobs">
          <RunningJobsPanel onSelect={onSelect} selectedId={selectedId} />
          <RecentList onSelect={onSelect} selectedId={selectedId} />
        </Pane>
        {selectedId !== null && isManualSelection && (
          <StackedView title={`Job #${selectedId}`} backLabel="Back to jobs" onBack={close}>
            <ActiveJobCard jobId={selectedId} />
          </StackedView>
        )}
      </Screen>
    );
  }

  return (
    <Screen name="jobs" layout={layout}>
      {layout === "ultra" ? (
        <>
          <Pane label="Running and queued jobs">
            <RunningJobsPanel onSelect={onSelect} selectedId={selectedId} showIdle />
          </Pane>
          <Pane label="All jobs">
            <RecentList onSelect={onSelect} selectedId={selectedId} />
          </Pane>
        </>
      ) : (
        <Pane label="Jobs">
          <RunningJobsPanel onSelect={onSelect} selectedId={selectedId} />
          <RecentList onSelect={onSelect} selectedId={selectedId} />
        </Pane>
      )}
      {selectedId !== null ? (
        <Pane label="Job details">
          <ActiveJobCard jobId={selectedId} onClose={close} />
        </Pane>
      ) : (
        <Pane label="Job details" className="pane-empty">
          <EmptyState
            compact
            title="Pick a job"
            body="Its chapters, progress and errors show here."
          />
        </Pane>
      )}
    </Screen>
  );
}
