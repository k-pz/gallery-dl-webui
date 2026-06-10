import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { findCall, jsonResponse, methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { TargetsList } from "./TargetsList";

afterEach(() => {
  vi.unstubAllGlobals();
});

function target(overrides: Record<string, unknown>) {
  return {
    id: 1,
    url: "https://example/a",
    name: "Series A",
    extractor: "fake",
    output_dir: null,
    watched: false,
    watch_period: null,
    last_polled_at: null,
    created_at: "2026-06-01T00:00:00+00:00",
    tags: [],
    reading_direction: null,
    series_status: null,
    last_download_id: 10,
    last_status: "completed",
    last_finished_at: "2026-06-01T01:00:00+00:00",
    last_created_at: "2026-06-01T00:30:00+00:00",
    download_count: 1,
    ...overrides,
  };
}

function mockLibrary(targets: unknown[]) {
  return mockFetch(async (input, init) => {
    const url = urlOf(input);
    if (url.includes("/api/targets/poll-watched")) {
      return jsonResponse({ scheduled: 1, skipped_active: 0 });
    }
    if (url.includes("/api/targets")) return jsonResponse(targets);
    if (url.includes("/api/config")) return jsonResponse({ default_watch_period: "1d" });
    return jsonResponse({}, 200) ?? init;
  });
}

describe("TargetsList refresh-watched button", () => {
  it("posts to poll-watched when clicked", async () => {
    const spy = mockLibrary([
      target({ id: 1, watched: true }),
      target({
        id: 2,
        url: "https://example/b",
        name: "Series B",
        watched: true,
        series_status: "Ended",
      }),
    ]);

    renderWithProviders(<TargetsList />);
    const button = await screen.findByRole("button", { name: "Refresh watched" });
    expect(button).toBeEnabled();

    await userEvent.click(button);

    await waitFor(() => {
      const call = findCall(
        spy,
        (input, init) =>
          urlOf(input).includes("/api/targets/poll-watched") && methodOf(input, init) === "POST",
      );
      expect(call).toBeDefined();
    });
  });

  it("is disabled when no watched series could be refreshed", async () => {
    mockLibrary([
      target({ id: 1, watched: false }),
      target({
        id: 2,
        url: "https://example/b",
        name: "Series B",
        watched: true,
        series_status: "Ended",
      }),
    ]);

    renderWithProviders(<TargetsList />);
    const button = await screen.findByRole("button", { name: "Refresh watched" });
    expect(button).toBeDisabled();
  });
});
