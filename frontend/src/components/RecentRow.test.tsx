import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Download } from "../api/types.gen";
import { renderWithProviders } from "../test/render";
import { RecentRow } from "./RecentRow";

function makeJob(overrides: Partial<Download>): Download {
  return {
    id: 1,
    url: "https://example/x",
    name: null,
    extractor: "fake",
    status: "completed",
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
    exit_code: 0,
    files_downloaded: 0,
    files_expected: null,
    chapters_total: 5,
    chapters_discovered: 5,
    chapters_failed: 0,
    error: null,
    postprocess_status: null,
    postprocess_chapters_packed: null,
    postprocess_error: null,
    output_dir: null,
    target_id: null,
    ...overrides,
  } as Download;
}

const noop = () => {};

describe("RecentRow chapter label", () => {
  it("appends the failed count when chapters failed", () => {
    renderWithProviders(
      <RecentRow
        item={makeJob({ chapters_total: 5, chapters_failed: 2 })}
        selected={false}
        cancelling={false}
        inflight={false}
        isCancelPending={false}
        isRequeuePending={false}
        onSelect={noop}
        onCancel={noop}
        onRequeue={noop}
      />,
    );
    expect(screen.getByText(/2 failed/)).toBeInTheDocument();
  });

  it("omits the failed suffix when nothing failed", () => {
    renderWithProviders(
      <RecentRow
        item={makeJob({ chapters_total: 5, chapters_failed: 0 })}
        selected={false}
        cancelling={false}
        inflight={false}
        isCancelPending={false}
        isRequeuePending={false}
        onSelect={noop}
        onCancel={noop}
        onRequeue={noop}
      />,
    );
    expect(screen.queryByText(/failed/)).not.toBeInTheDocument();
    expect(screen.getByText("5 chapters")).toBeInTheDocument();
  });
});
