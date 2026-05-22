import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bodyOf, jsonResponse, methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { MaintenancePanel } from "./MaintenancePanel";

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

type UpdateCheck = {
  branch: string | null;
  current_sha: string | null;
  latest_sha: string | null;
  latest_message: string | null;
  latest_committed_at: string | null;
  behind: boolean | null;
  reason: string | null;
};

const DEFAULT_UPDATE_CHECK: UpdateCheck = {
  branch: "main",
  current_sha: "abc1234567",
  latest_sha: "abc1234567",
  latest_message: "feat: x",
  latest_committed_at: "2026-05-22T10:00:00Z",
  behind: false,
  reason: null,
};

function jobsHandler(opts: {
  jobs: Job[];
  nextId: { value: number };
  progress: Record<number, { status: string; total: number; done: number; lines: string[] }>;
  postedKinds?: string[];
  updateCheck?: UpdateCheck;
}) {
  return async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
    const u = urlOf(input);
    if (u.includes("/api/maintenance/update-check")) {
      return jsonResponse(opts.updateCheck ?? DEFAULT_UPDATE_CHECK);
    }
    const progressMatch = u.match(/\/api\/maintenance\/jobs\/(\d+)\/progress/);
    if (progressMatch) {
      const id = Number(progressMatch[1]);
      const snap = opts.progress[id];
      if (!snap) return new Response("not found", { status: 404 });
      return jsonResponse(snap);
    }
    if (u.includes("/api/maintenance/jobs")) {
      if (methodOf(input, init) === "POST") {
        const body = JSON.parse(await bodyOf(input, init));
        opts.postedKinds?.push(body.kind);
        const created: Job = {
          id: opts.nextId.value++,
          kind: body.kind,
          status: "pending",
          created_at: "2025-01-02T00:00:00",
          started_at: null,
          finished_at: null,
          result: null,
          error: null,
        };
        opts.jobs.unshift(created);
        opts.progress[created.id] = {
          status: "pending",
          total: 0,
          done: 0,
          lines: [],
        };
        return jsonResponse(created);
      }
      return jsonResponse(opts.jobs);
    }
    return new Response("not found", { status: 404 });
  };
}

describe("MaintenancePanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("schedules a chapter rename job", async () => {
    const nextId = { value: 2 };
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
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {
      1: { status: "completed", total: 5, done: 5, lines: ["done"] },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    await screen.findByText("rename_chapters");
    fireEvent.click(screen.getByRole("button", { name: /schedule chapter rename/i }));
    await waitFor(() => {
      expect(screen.getAllByText("rename_chapters").length).toBeGreaterThan(1);
    });
  });

  it("renders a live log tail for the latest job", async () => {
    const nextId = { value: 2 };
    const jobs: Job[] = [
      {
        id: 1,
        kind: "rename_chapters",
        status: "running",
        created_at: "2025-01-01T00:00:00",
        started_at: "2025-01-01T00:00:01",
        finished_at: null,
        result: null,
        error: null,
      },
    ];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {
      1: {
        status: "running",
        total: 3,
        done: 1,
        lines: ["scanning… found 3 archive(s)", "renamed: Series/c1.cbz -> Series/Series_001.cbz"],
      },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    await screen.findByText(/Job #1/);
    await waitFor(() => {
      expect(screen.getByText(/1 \/ 3/)).toBeInTheDocument();
    });
    expect(screen.getByText(/scanning… found 3 archive\(s\)/)).toBeInTheDocument();
  });

  it("schedules a regenerate-series-metadata job from the new button", async () => {
    const nextId = { value: 1 };
    const jobs: Job[] = [];
    const postedKinds: string[] = [];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {};
    mockFetch(jobsHandler({ jobs, nextId, progress, postedKinds }));

    renderWithProviders(<MaintenancePanel />);

    fireEvent.click(screen.getByRole("button", { name: /regenerate series metadata/i }));
    await waitFor(() => {
      expect(postedKinds).toContain("regenerate_series_metadata");
    });
  });

  it("surfaces 'update available' banner when behind is true", async () => {
    const nextId = { value: 1 };
    const jobs: Job[] = [];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {};
    mockFetch(
      jobsHandler({
        jobs,
        nextId,
        progress,
        updateCheck: {
          branch: "main",
          current_sha: "old1111",
          latest_sha: "new2222abc",
          latest_message: "fix: shiny",
          latest_committed_at: "2026-05-22T10:00:00Z",
          behind: true,
          reason: null,
        },
      }),
    );

    renderWithProviders(<MaintenancePanel />);

    await screen.findByText(/update available — new2222/i);
    expect(screen.getByText("fix: shiny")).toBeInTheDocument();
  });

  it("schedules update_lxc only after the second-stage confirm", async () => {
    const nextId = { value: 1 };
    const jobs: Job[] = [];
    const postedKinds: string[] = [];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {};
    mockFetch(jobsHandler({ jobs, nextId, progress, postedKinds }));

    renderWithProviders(<MaintenancePanel />);

    // Stage 1: the open button doesn't schedule by itself.
    fireEvent.click(screen.getByRole("button", { name: /update lxc…/i }));
    expect(postedKinds).toEqual([]);

    // Stage 2: explicit "Yes, update now" confirms.
    fireEvent.click(screen.getByRole("button", { name: /yes, update now/i }));
    await waitFor(() => {
      expect(postedKinds).toContain("update_lxc");
    });

    // Post-schedule banner explains what happens next.
    await screen.findByText(/update queued/i);
  });

  it("switches the log to the row the user clicks", async () => {
    const nextId = { value: 3 };
    const jobs: Job[] = [
      {
        id: 2,
        kind: "rename_chapters",
        status: "running",
        created_at: "2025-01-02T00:00:00",
        started_at: "2025-01-02T00:00:01",
        finished_at: null,
        result: null,
        error: null,
      },
      {
        id: 1,
        kind: "rename_chapters",
        status: "completed",
        created_at: "2025-01-01T00:00:00",
        started_at: "2025-01-01T00:00:01",
        finished_at: "2025-01-01T00:00:02",
        result: { renamed: 4 },
        error: null,
      },
    ];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {
      2: { status: "running", total: 10, done: 3, lines: ["working on job 2"] },
      1: { status: "completed", total: 4, done: 4, lines: ["done: {renamed: 4}"] },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    // Defaults to the most recent job (id 2).
    await screen.findByText(/Job #2/);
    expect(screen.getByText(/working on job 2/)).toBeInTheDocument();

    // Click the older row → log should swap to job 1.
    const row1 = screen.getByLabelText("Select maintenance job 1");
    fireEvent.click(within(row1).getByText("1"));
    await screen.findByText(/Job #1/);
    expect(screen.getByText(/done: \{renamed: 4\}/)).toBeInTheDocument();
  });
});
