import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { RunningJobsPanel } from "./RunningJobsPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RunningJobsPanel progress label", () => {
  it("spells the chapters unit", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/api/downloads"))
        return jsonResponse([
          {
            id: 7,
            url: "https://example/x",
            name: "Example",
            extractor: "fake",
            status: "running",
            created_at: "2026-01-01T00:00:00Z",
            started_at: "2026-01-01T00:00:01Z",
            finished_at: null,
            exit_code: null,
            files_downloaded: 0,
            files_expected: null,
            chapters_total: 40,
            chapters_discovered: 40,
            chapters_failed: 0,
            error: null,
            postprocess_status: null,
            postprocess_chapters_packed: 12,
            postprocess_error: null,
            output_dir: null,
            target_id: null,
          },
        ]);
      return jsonResponse({});
    });

    renderWithProviders(<RunningJobsPanel onSelect={() => {}} selectedId={null} />);

    await waitFor(() => expect(screen.getByText("12/40 chapters")).toBeInTheDocument());
    expect(screen.queryByText(/ ch\./)).not.toBeInTheDocument();
  });
});
