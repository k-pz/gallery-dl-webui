import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Download } from "../api/types.gen";
import { renderWithProviders } from "../test/render";

vi.mock("../api/@tanstack/react-query.gen", () => ({
  listDownloadsOptions: () => ({ queryKey: ["downloads"], queryFn: async () => mockList }),
}));

let mockList: Download[] = [];

function makeRunning(overrides: Partial<Download>): Download {
  return {
    id: 1,
    url: "https://example/series-x",
    name: "Series X",
    extractor: "fake",
    status: "running",
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    exit_code: null,
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

afterEach(() => {
  mockList = [];
  vi.unstubAllGlobals();
});

describe("RunningJobsPanel progress label", () => {
  it("spells the chapters unit", async () => {
    mockList = [
      makeRunning({
        id: 7,
        url: "https://example/x",
        name: "Example",
        started_at: "2026-01-01T00:00:01Z",
        chapters_total: 40,
        chapters_discovered: 40,
        chapters_failed: 0,
        postprocess_chapters_packed: 12,
      }),
    ];

    const { RunningJobsPanel } = await import("./RunningJobsPanel");
    renderWithProviders(<RunningJobsPanel onSelect={() => {}} selectedId={null} />);

    await waitFor(() => expect(screen.getByText("12/40 chapters")).toBeInTheDocument());
    expect(screen.queryByText(/ ch\./)).not.toBeInTheDocument();
  });
});

describe("RunningJobsPanel URL subtitle", () => {
  it("renders the URL as a subtitle when the series has a name", async () => {
    mockList = [makeRunning({ id: 7, name: "Series X", url: "https://example/series-x" })];
    const { RunningJobsPanel } = await import("./RunningJobsPanel");
    renderWithProviders(<RunningJobsPanel onSelect={() => {}} selectedId={null} />);
    expect(await screen.findByText("Series X")).toBeInTheDocument();
    expect(screen.getByText("https://example/series-x")).toBeInTheDocument();
  });

  it("omits the subtitle when there is no name (URL is already the heading)", async () => {
    mockList = [makeRunning({ id: 8, name: null, url: "https://example/no-name" })];
    const { RunningJobsPanel } = await import("./RunningJobsPanel");
    renderWithProviders(<RunningJobsPanel onSelect={() => {}} selectedId={null} />);
    expect(await screen.findAllByText("https://example/no-name")).toHaveLength(1);
  });
});
