import { Tabs } from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { useRef } from "react";
import type { Target } from "../api/types.gen";
import type { LibraryLayout } from "../hooks/useLibraryLayout";
import { useModalFocusTrap } from "../hooks/useModalFocusTrap";
import { displayName } from "../lib/library";
import { volumeSourceUrl } from "../lib/volumeFill";
import { EpubPacker } from "./EpubPacker";
import { ICON_SIZE, IconChevronDown } from "./Icons";
import { SeriesHeader } from "./SeriesHeader";
import { SeriesRuns } from "./SeriesRuns";
import { SeriesSettings, SeriesStats } from "./SeriesSettings";

type DetailTab = "details" | "epub" | "runs";

/**
 * The selected series. On ultra-wide screens its details and its EPUB
 * packer sit in two columns side by side; narrower, they share one pane
 * behind tabs; on phones the pane becomes a full-screen view over the list
 * with a back button.
 */
export function SeriesDetail({
  target,
  layout,
  onOpenJob,
  onClose,
}: {
  target: Target;
  layout: LibraryLayout;
  onOpenJob: (jobId: number) => void;
  /** Leave the series (phone back button, or after it was removed). */
  onClose: () => void;
}) {
  if (layout === "ultra") {
    return (
      <>
        <section className="lib-pane lib-details" aria-label="Series details">
          <SeriesHeader target={target} onOpenJob={onOpenJob} onRemoved={onClose} />
          <div className="lib-pane-scroll lib-details-body">
            <SeriesStats target={target} />
            <h3 className="lib-subhead">Settings</h3>
            <SeriesSettings target={target} />
            <h3 className="lib-subhead">Recent runs</h3>
            <SeriesRuns targetId={target.id} onOpenJob={onOpenJob} />
          </div>
        </section>
        <section className="lib-pane lib-packer" aria-label="EPUB books">
          <div className="lib-pane-title">
            <span className="app-section-kicker">EPUB books</span>
            <span className="lib-pane-title-name">{displayName(target)}</span>
          </div>
          <EpubPacker key={target.id} targetId={target.id} volumeSource={volumeSourceUrl(target)} />
        </section>
      </>
    );
  }
  return (
    <TabbedDetail
      target={target}
      stacked={layout === "stack"}
      onOpenJob={onOpenJob}
      onClose={onClose}
    />
  );
}

function TabbedDetail({
  target,
  stacked,
  onOpenJob,
  onClose,
}: {
  target: Target;
  stacked: boolean;
  onOpenJob: (jobId: number) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useLocalStorage<DetailTab>({
    key: "library-detail-tab",
    defaultValue: "details",
    getInitialValueInEffect: false,
  });
  const dialogRef = useRef<HTMLDivElement | null>(null);
  // On phones the series view covers the list like a pushed screen: focus
  // stays inside, Escape and the back button return to the list.
  useModalFocusTrap({ active: stacked, rootRef: dialogRef, onClose, lockScroll: true });
  const books = target.epub_book_count;
  const body = (
    <>
      {stacked && (
        <div className="lib-detail-back">
          <button
            type="button"
            className="lib-detail-back-btn"
            onClick={onClose}
            aria-label="Back to library"
          >
            <IconChevronDown size={ICON_SIZE.lg} className="lib-detail-back-icon" />
          </button>
          <span className="lib-detail-back-title">{displayName(target)}</span>
        </div>
      )}
      <SeriesHeader target={target} onOpenJob={onOpenJob} onRemoved={onClose} />
      <Tabs
        value={tab}
        onChange={(v) => v && setTab(v as DetailTab)}
        className="lib-detail-tabs"
        keepMounted={false}
      >
        <Tabs.List>
          <Tabs.Tab value="details">Details</Tabs.Tab>
          <Tabs.Tab value="epub">EPUB books{books ? ` · ${books}` : ""}</Tabs.Tab>
          <Tabs.Tab value="runs">Runs · {target.download_count ?? 0}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="details" className="lib-pane-scroll lib-details-body">
          <SeriesStats target={target} />
          <SeriesSettings target={target} />
        </Tabs.Panel>
        <Tabs.Panel value="epub" className="lib-detail-packer">
          <EpubPacker key={target.id} targetId={target.id} volumeSource={volumeSourceUrl(target)} />
        </Tabs.Panel>
        <Tabs.Panel value="runs" className="lib-pane-scroll lib-details-body">
          <SeriesRuns targetId={target.id} onOpenJob={onOpenJob} />
        </Tabs.Panel>
      </Tabs>
    </>
  );
  if (stacked) {
    return (
      <div
        ref={dialogRef}
        className="lib-pane lib-detail"
        data-stacked="true"
        role="dialog"
        aria-modal="true"
        aria-label={displayName(target)}
      >
        {body}
      </div>
    );
  }
  return (
    <section className="lib-pane lib-detail" aria-label="Series details">
      {body}
    </section>
  );
}
