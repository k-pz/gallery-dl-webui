import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { MaintenanceLog } from "./MaintenanceLog";

const PROGRESS = { status: "running", done: 2, total: 4, lines: ["line one", "line two"] };

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("MaintenanceLog expand", () => {
  it("scrolls the log box into view when expanded", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress")) return jsonResponse(PROGRESS);
      return jsonResponse({});
    });

    renderWithProviders(<MaintenanceLog jobId={1} startedAt={null} />);

    const toggle = await screen.findByRole("button", { name: /expand job log/i });
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();

    await userEvent.click(toggle);

    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ block: "nearest" }),
    );
  });

  it("uses an instant (non-smooth) scroll when the user prefers reduced motion", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }));
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress")) return jsonResponse(PROGRESS);
      return jsonResponse({});
    });

    renderWithProviders(<MaintenanceLog jobId={1} startedAt={null} />);

    const toggle = await screen.findByRole("button", { name: /expand job log/i });
    await userEvent.click(toggle);

    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled());
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto", block: "nearest" }),
    );
  });

  it("renders the live status badge with a cased label, not the raw token", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress")) return jsonResponse(PROGRESS);
      return jsonResponse({});
    });

    renderWithProviders(<MaintenanceLog jobId={1} startedAt={null} />);

    await screen.findByRole("button", { name: /expand job log/i });
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.queryByText("running")).not.toBeInTheDocument();
  });
});

describe("MaintenanceLog terminal state", () => {
  it("treats a cancelled job as terminal — the progress bar stops animating", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/progress"))
        return jsonResponse({ status: "cancelled", done: 2, total: 4, lines: ["cancelled"] });
      return jsonResponse({});
    });

    const { container } = renderWithProviders(<MaintenanceLog jobId={1} startedAt={null} />);

    // The badge already calls it "Cancelled"…
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    // …so the progress bar must not keep animating as if the job were still live.
    const section = container.querySelector(".mantine-Progress-section");
    expect(section).not.toBeNull();
    expect(section).not.toHaveAttribute("data-animated");
  });
});
