import { describe, expect, it, vi } from "vitest";
import { JobsTabBody } from "./App";
import { jsonResponse, mockFetch } from "./test/mocks";
import { renderWithProviders } from "./test/render";

const useMediaQueryMock = vi.fn();
vi.mock("@mantine/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mantine/hooks")>();
  return { ...actual, useMediaQuery: (...args: unknown[]) => useMediaQueryMock(...args) };
});

describe("JobsTabBody viewport-aware grid", () => {
  function arrange() {
    mockFetch(async () => jsonResponse([]));
  }

  it("renders the two-column .jobs-grid when wide and a job is selected", () => {
    useMediaQueryMock.mockReturnValue(true);
    arrange();
    const { container } = renderWithProviders(
      <JobsTabBody selectedId={7} onSelect={() => {}} hasAnyActive />,
    );
    expect(container.querySelector(".jobs-grid")).not.toBeNull();
  });

  it("never enters .jobs-grid on a narrow viewport even with a selection", () => {
    useMediaQueryMock.mockReturnValue(false);
    arrange();
    const { container } = renderWithProviders(
      <JobsTabBody selectedId={7} onSelect={() => {}} hasAnyActive />,
    );
    expect(container.querySelector(".jobs-grid")).toBeNull();
    expect(useMediaQueryMock).toHaveBeenCalledWith(expect.stringContaining("min-width"), true);
  });
});
