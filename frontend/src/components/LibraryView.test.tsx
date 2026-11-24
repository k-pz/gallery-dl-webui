import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Target } from "../api/types.gen";
import { bodyOf, findCall, jsonResponse, methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { LibraryView } from "./LibraryView";

function target(overrides: Partial<Target>): Target {
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
    metadata_source_url: null,
    last_download_id: 10,
    last_status: "completed",
    last_finished_at: "2026-06-01T01:00:00+00:00",
    last_created_at: "2026-06-01T00:30:00+00:00",
    download_count: 1,
    chapter_count: 0,
    epub_book_count: 0,
    epub_pending_count: 0,
    ...overrides,
  };
}

const LIBRARY = [
  target({
    id: 1,
    name: "Series A",
    watched: true,
    chapter_count: 120,
    epub_book_count: 12,
    epub_pending_count: 3,
    last_finished_at: "2026-06-03T00:00:00+00:00",
  }),
  target({ id: 2, name: "Series B", url: "https://example/b", chapter_count: 40 }),
];

function mockLibrary(targets: Target[] = LIBRARY) {
  return mockFetch(async (input, init) => {
    const url = urlOf(input);
    if (url.includes("/api/targets/poll-watched")) {
      return jsonResponse({ scheduled: 1, skipped_active: 0 });
    }
    if (methodOf(input, init) === "PATCH") return jsonResponse(targets[0]);
    if (url.includes("/epub")) {
      return jsonResponse({
        target_id: 1,
        series: "Series A",
        series_dir: null,
        export_dir: "/data/epub",
        chapters: [],
        books: [],
        unassigned: [],
        suggested_books: [],
      });
    }
    if (url.includes("/api/targets")) return jsonResponse(targets);
    if (url.includes("/api/downloads")) return jsonResponse([]);
    if (url.includes("/api/config")) return jsonResponse({ default_watch_period: "1d" });
    return jsonResponse([]);
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/library");
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LibraryView", () => {
  it("lists series with their chapter and EPUB counts and opens the newest", async () => {
    mockLibrary();
    renderWithProviders(<LibraryView tab="library" onOpenJob={() => {}} />);

    const list = await screen.findByRole("region", { name: "Series" });
    expect(await within(list).findByText("120 ch")).toBeInTheDocument();
    expect(within(list).getByText("3 to export")).toBeInTheDocument();
    // Wide layouts show the most recent series without a click.
    expect(await screen.findByRole("heading", { name: "Series A" })).toBeInTheDocument();
    // An auto-selected series stays out of the URL.
    expect(window.location.search).toBe("");
  });

  it("filters with the chips and mirrors a picked series into the URL", async () => {
    mockLibrary();
    renderWithProviders(<LibraryView tab="library" onOpenJob={() => {}} />);

    await userEvent.click(await screen.findByRole("button", { name: /To export/ }));
    expect(screen.queryByRole("button", { name: /Series B/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^All/ }));

    await userEvent.click(screen.getByRole("button", { name: /Series B/ }));
    expect(await screen.findByRole("heading", { name: "Series B" })).toBeInTheDocument();
    expect(window.location.search).toBe("?series=2");
  });

  it("opens the series from a ?series= deep link", async () => {
    window.history.replaceState(null, "", "/library?series=2");
    mockLibrary();
    renderWithProviders(<LibraryView tab="library" onOpenJob={() => {}} />);
    expect(await screen.findByRole("heading", { name: "Series B" })).toBeInTheDocument();
  });

  it("refreshes watched series from the list header", async () => {
    const spy = mockLibrary();
    renderWithProviders(<LibraryView tab="library" onOpenJob={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: /refresh watched/i }));
    await waitFor(() =>
      expect(findCall(spy, (i) => urlOf(i).includes("/api/targets/poll-watched"))).toBeDefined(),
    );
  });

  it("opens the last job and saves an edited metadata source on blur", async () => {
    const onOpenJob = vi.fn();
    const spy = mockLibrary();
    renderWithProviders(<LibraryView tab="library" onOpenJob={onOpenJob} />);

    await userEvent.click(await screen.findByRole("button", { name: /Job #10/ }));
    expect(onOpenJob).toHaveBeenCalledWith(10);

    const input = await screen.findByLabelText("Metadata source URL");
    await userEvent.type(input, "https://mangadex.org/title/abc");
    fireEvent.blur(input);
    await waitFor(() => {
      const call = findCall(spy, (i, init) => methodOf(i, init) === "PATCH");
      expect(call).toBeDefined();
    });
    const [i, init] = findCall(spy, (x, y) => methodOf(x, y) === "PATCH") as Parameters<
      typeof fetch
    >;
    expect(JSON.parse(await bodyOf(i, init))).toEqual({
      metadata_source_url: "https://mangadex.org/title/abc",
    });
  });

  it("explains an empty library", async () => {
    mockLibrary([]);
    renderWithProviders(<LibraryView tab="library" onOpenJob={() => {}} />);
    expect(await screen.findByText("Your library is empty")).toBeInTheDocument();
  });
});
