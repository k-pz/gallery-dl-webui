import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { ProgressCard } from "./ProgressCard";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PROGRESS = {
  status: "completed",
  files_expected: 2,
  files_present: 1,
  chapters_discovered: 3,
  chapters_needed: 2,
  chapters_downloaded: 1,
  chapters_failed: 1,
  chapters_skipped: 0,
  chapters: [
    {
      name: "1",
      files_total: 12,
      files_present: 12,
      stage: "downloaded",
      status: "downloaded",
      pages: 12,
      title: "Intro",
      date: "2026-01-01",
      error: null,
    },
    {
      name: "2",
      files_total: 1,
      files_present: 0,
      stage: "downloading",
      status: "failed",
      pages: 0,
      title: null,
      date: null,
      error: "403 Forbidden",
    },
  ],
};

describe("ProgressCard (terminal job)", () => {
  it("shows the discovered/needed/downloaded/failed summary and outcome badges", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress")) return jsonResponse(PROGRESS);
      return jsonResponse({});
    });

    renderWithProviders(<ProgressCard jobId={1} status="completed" startedAt={null} />);

    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    // Per-chapter badges from outcome status.
    expect(screen.getByText("Downloaded")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    // Summary counts present somewhere in the card.
    expect(screen.getByText(/discovered 3/i)).toBeInTheDocument();
    expect(screen.getByText(/failed 1/i)).toBeInTheDocument();
  });
});
