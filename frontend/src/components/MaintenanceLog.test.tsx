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
});
