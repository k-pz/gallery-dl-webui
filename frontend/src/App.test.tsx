import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobsView } from "./components/JobsView";
import { jsonResponse, mockFetch } from "./test/mocks";
import { renderWithProviders } from "./test/render";

/** Make one media query match (jsdom's default matches none). */
function viewport(match: string | null) {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: query === match,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as MediaQueryList,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("JobsView layout", () => {
  function arrange() {
    mockFetch(async () => jsonResponse([]));
  }

  it("shows the list beside an empty detail pane until a job is picked", () => {
    arrange();
    viewport(null);
    const { container } = renderWithProviders(
      <JobsView selectedId={null} isManualSelection={false} onSelect={() => {}} />,
    );
    const screenEl = container.querySelector('.screen[data-screen="jobs"]');
    expect(screenEl).toHaveAttribute("data-layout", "split");
    expect(screen.getByRole("region", { name: "Jobs" })).toBeInTheDocument();
    expect(screen.getByText("Pick a job")).toBeInTheDocument();
  });

  it("keeps the same screen root when a job is selected", () => {
    arrange();
    viewport(null);
    const { container, rerender } = renderWithProviders(
      <JobsView selectedId={null} isManualSelection={false} onSelect={() => {}} />,
    );
    const before = container.querySelector(".screen");
    rerender(<JobsView selectedId={7} isManualSelection onSelect={() => {}} />);
    expect(container.querySelector(".screen")).toBe(before);
    expect(screen.getByRole("region", { name: "Job details" })).toBeInTheDocument();
    expect(screen.queryByText("Pick a job")).toBeNull();
  });

  it("splits running and history into their own panes on ultra-wide screens", () => {
    arrange();
    viewport("(min-width: 2400px)");
    renderWithProviders(
      <JobsView selectedId={null} isManualSelection={false} onSelect={() => {}} />,
    );
    expect(screen.getByRole("region", { name: "Running and queued jobs" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "All jobs" })).toBeInTheDocument();
    expect(screen.getByText("Nothing running or queued.")).toBeInTheDocument();
  });

  it("opens a picked job full screen on phones and goes back with the back button", () => {
    arrange();
    viewport("(max-width: 899px)");
    const onSelect = vi.fn();
    renderWithProviders(<JobsView selectedId={7} isManualSelection onSelect={onSelect} />);
    expect(screen.getByRole("dialog", { name: "Job #7" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to jobs" }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("does not cover the list on phones for the auto-selected running job", () => {
    arrange();
    viewport("(max-width: 899px)");
    renderWithProviders(<JobsView selectedId={7} isManualSelection={false} onSelect={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
