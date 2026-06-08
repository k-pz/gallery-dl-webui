import { describe, expect, it } from "vitest";
import { JobsTabBody } from "./App";
import { jsonResponse, mockFetch } from "./test/mocks";
import { renderWithProviders } from "./test/render";

describe("JobsTabBody layout", () => {
  function arrange() {
    mockFetch(async () => jsonResponse([]));
  }

  it("always renders the .jobs-grid; selection only flags it and mounts the detail", () => {
    arrange();
    const { container, rerender } = renderWithProviders(
      <JobsTabBody selectedId={null} onSelect={() => {}} hasAnyActive />,
    );

    // No selection: the grid is already the structure (single column via CSS),
    // with no selection flag.
    const gridBefore = container.querySelector(".jobs-grid");
    expect(gridBefore).not.toBeNull();
    expect(gridBefore).not.toHaveAttribute("data-has-selection");

    // Selecting a job must reuse the SAME root node (no remount → the list and
    // detail keep their state) and just flag master-detail mode.
    rerender(<JobsTabBody selectedId={7} onSelect={() => {}} hasAnyActive />);
    const gridAfter = container.querySelector(".jobs-grid");
    expect(gridAfter).toBe(gridBefore);
    expect(gridAfter).toHaveAttribute("data-has-selection", "true");
  });

  it("does not gate the layout on a viewport media query", () => {
    // jsdom's matchMedia reports no match; if layout were JS-gated on a min-width
    // query, a selection would fall back to the single-column stack and there'd
    // be no .jobs-grid. CSS-driven layout keeps the grid regardless of viewport.
    arrange();
    const { container } = renderWithProviders(
      <JobsTabBody selectedId={7} onSelect={() => {}} hasAnyActive />,
    );
    expect(container.querySelector(".jobs-grid")).not.toBeNull();
  });
});
