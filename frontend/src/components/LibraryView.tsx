import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { listTargetsOptions } from "../api/@tanstack/react-query.gen";
import { useLibraryLayout } from "../hooks/useLibraryLayout";
import { initialSeriesIdFromUrl, useSyncSeriesParam } from "../hooks/useRouteSeries";
import type { Tab } from "../hooks/useRouteTab";
import { DEFAULT_LIBRARY_FILTERS, type LibraryFilters, visibleTargets } from "../lib/library";
import { REFETCH_LIST_MS } from "../lib/polling";
import { ActivityRail } from "./ActivityRail";
import { EmptyState } from "./EmptyState";
import { SeriesDetail } from "./SeriesDetail";
import { SeriesList } from "./SeriesList";

/**
 * The Library tab as one screen: the series list beside the selected
 * series, each pane scrolling on its own so nothing pushes the rest of the
 * page down. See useLibraryLayout for the width tiers.
 */
export function LibraryView({ tab, onOpenJob }: { tab: Tab; onOpenJob: (jobId: number) => void }) {
  const { layout, showRail } = useLibraryLayout();
  const { data: targets, isLoading } = useQuery({
    ...listTargetsOptions(),
    refetchInterval: REFETCH_LIST_MS,
  });
  const [filters, setFilters] = useState<LibraryFilters>(DEFAULT_LIBRARY_FILTERS);
  const [picked, setPicked] = useState<number | null>(initialSeriesIdFromUrl);

  const all = targets ?? [];
  const visible = useMemo(() => visibleTargets(targets ?? [], filters), [targets, filters]);
  const pickedTarget = picked !== null ? all.find((t) => t.id === picked) : undefined;
  // Wide layouts always show a series: the picked one, else the first in
  // the list. Phones show the list until one is picked.
  const selected = pickedTarget ?? (layout === "stack" ? undefined : visible[0]);
  useSyncSeriesParam(tab, pickedTarget ? pickedTarget.id : null);

  return (
    <div className="lib-view" data-layout={layout} data-rail={showRail ? "true" : undefined}>
      <SeriesList
        targets={all}
        visible={visible}
        filters={filters}
        onFiltersChange={setFilters}
        selectedId={selected?.id ?? null}
        onSelect={setPicked}
        isLoading={isLoading}
      />
      {selected ? (
        <SeriesDetail
          target={selected}
          layout={layout}
          onOpenJob={onOpenJob}
          onClose={() => setPicked(null)}
        />
      ) : (
        layout !== "stack" && (
          <section className="lib-pane lib-detail lib-detail-empty" aria-label="Series details">
            <EmptyState
              compact
              title={all.length === 0 ? "Add a series to get started" : "Pick a series"}
            />
          </section>
        )
      )}
      {layout === "ultra" && showRail && <ActivityRail targets={all} onOpenJob={onOpenJob} />}
    </div>
  );
}
