import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { ActiveJobCard } from "./ActiveJobCard";

afterEach(() => {
  vi.unstubAllGlobals();
});

const BASE_JOB = {
  id: 7,
  url: "https://example/series",
  name: "Example Series",
  extractor: "fake",
  created_at: "2026-06-10T10:00:00+00:00",
  started_at: "2026-06-10T10:01:00+00:00",
  finished_at: null as string | null,
  exit_code: null as number | null,
  files_downloaded: 0,
  files_expected: null,
  chapters_total: null,
  chapters_discovered: null,
  chapters_failed: null,
  error: null,
  postprocess_status: null as string | null,
  postprocess_chapters_packed: null,
  postprocess_error: null,
  output_dir: null,
  target_id: 1,
};

const EMPTY_PROGRESS = {
  files_expected: null,
  files_present: 0,
  chapters_discovered: null,
  chapters_needed: null,
  chapters_downloaded: 0,
  chapters_failed: 0,
  chapters_skipped: 0,
  chapters: [],
};

function mockJob(job: Record<string, unknown>) {
  mockFetch(async (input) => {
    const url = urlOf(input);
    if (url.includes("/progress")) {
      return jsonResponse({ ...EMPTY_PROGRESS, status: job.status });
    }
    if (url.includes("/api/downloads/")) return jsonResponse(job);
    return jsonResponse({});
  });
}

describe("ActiveJobCard (finished job)", () => {
  it("labels the card 'job' and shows a Completed pill instead of the stepper", async () => {
    mockJob({
      ...BASE_JOB,
      status: "completed",
      finished_at: "2026-06-10T10:15:00+00:00",
      exit_code: 0,
      postprocess_status: "completed",
    });
    renderWithProviders(<ActiveJobCard jobId={7} />);

    expect(await screen.findByText("Example Series")).toBeInTheDocument();
    expect(screen.getByText("job")).toBeInTheDocument();
    expect(screen.queryByText("active job")).not.toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    // The lifecycle stepper is for in-flight jobs only.
    expect(screen.queryByText(/Step \d of \d/)).not.toBeInTheDocument();
  });

  it("shows started/finished timestamps and duration, but no exit code", async () => {
    mockJob({
      ...BASE_JOB,
      status: "completed",
      finished_at: "2026-06-10T10:15:00+00:00",
      exit_code: 0,
      postprocess_status: "completed",
    });
    renderWithProviders(<ActiveJobCard jobId={7} />);

    expect(await screen.findByText("Started")).toBeInTheDocument();
    expect(screen.getByText("Finished")).toBeInTheDocument();
    expect(screen.getByText("Duration")).toBeInTheDocument();
    expect(screen.getByText("14m")).toBeInTheDocument();
    expect(screen.queryByText("Exit code")).not.toBeInTheDocument();
  });

  it("shows a Failed pill for failed jobs", async () => {
    mockJob({
      ...BASE_JOB,
      status: "failed",
      finished_at: "2026-06-10T10:05:00+00:00",
      exit_code: 1,
      error: "boom",
    });
    renderWithProviders(<ActiveJobCard jobId={7} />);

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("job")).toBeInTheDocument();
    expect(screen.queryByText("Exit code")).not.toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});

describe("ActiveJobCard (active job)", () => {
  it("keeps the 'active job' label and lifecycle stepper while running", async () => {
    mockJob({ ...BASE_JOB, status: "running" });
    renderWithProviders(<ActiveJobCard jobId={7} />);

    expect(await screen.findByText("active job")).toBeInTheDocument();
    expect(screen.getByText(/Step 3 of 6/)).toBeInTheDocument();
    // No finish data yet — only the start timestamp is shown.
    expect(screen.getByText("Started")).toBeInTheDocument();
    expect(screen.queryByText("Finished")).not.toBeInTheDocument();
    expect(screen.queryByText("Duration")).not.toBeInTheDocument();
  });
});
