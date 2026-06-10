import { screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { ProgressCard } from "./ProgressCard";

// jsdom has no layout, so every element measures 0×0 and the virtualized
// chapter list would compute an empty window. Report fixed sizes (the
// virtualizer reads offsetWidth/offsetHeight for the viewport and
// getBoundingClientRect for row measurement) so it renders rows.
const offsetWidthDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");
const offsetHeightDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 400 });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 220 });
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    width: 400,
    height: 220,
    top: 0,
    left: 0,
    bottom: 220,
    right: 400,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
});

afterAll(() => {
  vi.restoreAllMocks();
  if (offsetWidthDesc) Object.defineProperty(HTMLElement.prototype, "offsetWidth", offsetWidthDesc);
  if (offsetHeightDesc) {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", offsetHeightDesc);
  }
});

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

describe("ProgressCard transient labels", () => {
  it("shows 'fetching…' before the manifest is ready", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({
          status: "running",
          files_expected: null,
          files_present: 0,
          chapters_discovered: null,
          chapters_needed: null,
          chapters_downloaded: 0,
          chapters_failed: 0,
          chapters_skipped: 0,
          chapters: [],
        });
      return jsonResponse({});
    });
    renderWithProviders(<ProgressCard jobId={2} status="running" startedAt={null} />);
    expect(await screen.findByText("fetching…")).toBeInTheDocument();
  });

  it("labels a nameless chapter as (untitled)", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({
          status: "completed",
          files_expected: 1,
          files_present: 1,
          chapters_discovered: 1,
          chapters_needed: 1,
          chapters_downloaded: 1,
          chapters_failed: 0,
          chapters_skipped: 0,
          chapters: [
            {
              name: "",
              files_total: 1,
              files_present: 1,
              stage: "downloaded",
              status: "downloaded",
              pages: 1,
              title: null,
              date: null,
              error: null,
            },
          ],
        });
      return jsonResponse({});
    });
    renderWithProviders(<ProgressCard jobId={3} status="completed" startedAt={null} />);
    expect(await screen.findByText("(untitled)")).toBeInTheDocument();
  });
});

describe("ProgressCard chapter keys", () => {
  it("renders two same-named chapters without colliding React keys", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const nameless = {
      name: "",
      files_total: 1,
      files_present: 1,
      stage: "downloaded",
      status: "downloaded",
      pages: 1,
      title: null,
      date: null,
      error: null,
    };
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({
          status: "completed",
          files_expected: 2,
          files_present: 2,
          chapters_discovered: 2,
          chapters_needed: 2,
          chapters_downloaded: 2,
          chapters_failed: 0,
          chapters_skipped: 0,
          chapters: [nameless, nameless],
        });
      return jsonResponse({});
    });

    renderWithProviders(<ProgressCard jobId={5} status="completed" startedAt={null} />);

    // Both nameless rows must render…
    await waitFor(() => expect(screen.getAllByText("(untitled)")).toHaveLength(2));
    // …without React warning about duplicate keys (label-as-key collides here).
    const dupKeyWarning = errorSpy.mock.calls.some((args) =>
      args.some((a) => typeof a === "string" && a.includes("same key")),
    );
    errorSpy.mockRestore();
    expect(dupKeyWarning).toBe(false);
  });
});

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

  it("shows results without a progress bar or live labels", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress")) return jsonResponse(PROGRESS);
      return jsonResponse({});
    });

    renderWithProviders(<ProgressCard jobId={1} status="completed" startedAt={null} />);

    expect(await screen.findByText("1 / 2 chapters")).toBeInTheDocument();
    expect(screen.getByText("results")).toBeInTheDocument();
    expect(screen.queryByText("progress")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("never shows 'fetching…' for a finished job without a manifest", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({
          status: "failed",
          files_expected: null,
          files_present: 0,
          chapters_discovered: null,
          chapters_needed: null,
          chapters_downloaded: 0,
          chapters_failed: 0,
          chapters_skipped: 0,
          chapters: [],
        });
      return jsonResponse({});
    });

    renderWithProviders(<ProgressCard jobId={4} status="failed" startedAt={null} />);

    expect(
      await screen.findByText("No chapter details were recorded for this run."),
    ).toBeInTheDocument();
    expect(screen.queryByText("fetching…")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});

describe("ProgressCard chapter list virtualization", () => {
  it("renders only a window of rows for a very large series", async () => {
    const chapters = Array.from({ length: 1000 }, (_, i) => ({
      name: `ch ${i}`,
      files_total: 1,
      files_present: 1,
      stage: "downloaded",
      status: "downloaded",
      pages: 20,
      title: null,
      date: null,
      error: null,
    }));
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({
          status: "completed",
          files_expected: 1000,
          files_present: 1000,
          chapters_discovered: 1000,
          chapters_needed: 1000,
          chapters_downloaded: 1000,
          chapters_failed: 0,
          chapters_skipped: 0,
          chapters,
        });
      return jsonResponse({});
    });

    renderWithProviders(<ProgressCard jobId={7} status="completed" startedAt={null} />);

    expect(await screen.findByText("ch 0")).toBeInTheDocument();
    // The whole point of virtualizing: a 1000-chapter series must not put
    // 1000 rows in the DOM, only the visible window plus overscan.
    const rendered = screen.getAllByText(/^ch \d+$/).length;
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(100);
  });
});

describe("ProgressCard (active job)", () => {
  it("keeps the progress bar while the job is running", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({ ...PROGRESS, status: "running" });
      return jsonResponse({});
    });

    renderWithProviders(<ProgressCard jobId={6} status="running" startedAt={null} />);

    expect(await screen.findByText("1 / 2 chapters")).toBeInTheDocument();
    expect(screen.getByText("progress")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });
});
