import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { MaintenancePanel } from "./MaintenancePanel";

describe("MaintenancePanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("schedules a chapter rename job", async () => {
    type Job = {
      id: number;
      kind: string;
      status: string;
      created_at: string;
      started_at: string | null;
      finished_at: string | null;
      result: { renamed: number } | null;
      error: string | null;
    };
    let nextId = 2;
    const jobs: Job[] = [
      {
        id: 1,
        kind: "rename_chapters",
        status: "completed",
        created_at: "2025-01-01T00:00:00",
        started_at: "2025-01-01T00:00:01",
        finished_at: "2025-01-01T00:00:02",
        result: { renamed: 1 },
        error: null,
      },
    ];
    mockFetch(async (input, init) => {
      const u = urlOf(input);
      if (u.includes("/api/maintenance/jobs")) {
        if (methodOf(input, init) === "POST") {
          const created = {
            id: nextId++,
            kind: "rename_chapters",
            status: "pending",
            created_at: "2025-01-02T00:00:00",
            started_at: null,
            finished_at: null,
            result: null,
            error: null,
          };
          jobs.unshift(created);
          return new Response(JSON.stringify(created), { status: 200 });
        }
        return new Response(JSON.stringify(jobs), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });

    renderWithProviders(<MaintenancePanel />);

    await screen.findByText("rename_chapters");
    fireEvent.click(screen.getByRole("button", { name: /schedule chapter rename/i }));
    await waitFor(() => {
      expect(screen.getAllByText("rename_chapters").length).toBeGreaterThan(1);
    });
  });
});
