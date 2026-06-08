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

type ChangelogEntry = {
  title: string;
  body: string | null;
  ref: string;
  published_at: string | null;
  html_url: string | null;
};

type UpdateCheck = {
  branch: string | null;
  current_sha: string | null;
  current_version: string | null;
  tracked_ref: string | null;
  tracked_ref_is_default: boolean;
  latest_sha: string | null;
  latest_message: string | null;
  latest_committed_at: string | null;
  latest_version: string | null;
  behind: boolean | null;
  changelog: ChangelogEntry[];
  reason: string | null;
};

const DEFAULT_UPDATE_CHECK: UpdateCheck = {
  branch: "main",
  current_sha: "abc1234567",
  current_version: "1.0.0",
  tracked_ref: "main",
  tracked_ref_is_default: true,
  latest_sha: "abc1234567",
  latest_message: "feat: x",
  latest_committed_at: "2026-05-22T10:00:00Z",
  latest_version: "v1.0.0",
  behind: false,
  changelog: [],
  reason: null,
};

function jobsHandler(opts: {
  jobs: Job[];
  nextId: { value: number };
  progress: Record<number, { status: string; total: number; done: number; lines: string[] }>;
  postedKinds?: string[];
  updateCheck?: UpdateCheck;
  previewRef?: string | null;
  onPreviewRefSet?: (ref: string | null) => void;
}) {
  return async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
    const u = urlOf(input);
    if (u.includes("/api/maintenance/update-check")) {
      return jsonResponse(opts.updateCheck ?? DEFAULT_UPDATE_CHECK);
    }
    if (u.includes("/api/maintenance/update-ref")) {
      if (methodOf(input, init) === "PUT") {
        const body = JSON.parse(await bodyOf(input, init));
        const next: string | null = body.ref ?? null;
        opts.onPreviewRefSet?.(next);
        return jsonResponse({ ref: next });
      }
      return jsonResponse({ ref: opts.previewRef ?? null });
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

  it("schedules an unwatch-ended-series job from the button", async () => {
    const nextId = { value: 1 };
    const jobs: Job[] = [];
    const postedKinds: string[] = [];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {};
    mockFetch(jobsHandler({ jobs, nextId, progress, postedKinds }));

    renderWithProviders(<MaintenancePanel />);

    fireEvent.click(screen.getByRole("button", { name: /unwatch ended series/i }));
    await waitFor(() => {
      expect(postedKinds).toContain("unwatch_ended_series");
    });
  });

  it("surfaces 'update available' banner with version delta when behind is true", async () => {
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
          current_version: "1.0.0",
          tracked_ref: "main",
          tracked_ref_is_default: true,
          latest_sha: "new2222abc",
          latest_message: "fix: shiny",
          latest_committed_at: "2026-05-22T10:00:00Z",
          latest_version: "v1.1.0",
          behind: true,
          changelog: [
            {
              title: "v1.1.0 — Shiny",
              body: "## Fixes\n- fix: shiny",
              ref: "v1.1.0",
              published_at: "2026-05-22T10:00:00Z",
              html_url: "https://example/release/v1.1.0",
            },
          ],
          reason: null,
        },
      }),
    );

    renderWithProviders(<MaintenancePanel />);

    // Headline is now a version delta, not a SHA.
    await screen.findByText(/update available/i);
    // The version chip is split across nodes — query a flat regex by joining.
    await waitFor(() => {
      const banner = document.body.textContent ?? "";
      expect(banner).toMatch(/v1\.0\.0\s*→\s*v1\.1\.0/);
    });
    // Expand the changelog and confirm the release title surfaces.
    fireEvent.click(screen.getByRole("button", { name: /show changelog/i }));
    await screen.findByText("v1.1.0 — Shiny");
  });

  it("surfaces preview-ref banner when tracked_ref_is_default is false", async () => {
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
        previewRef: "develop",
        updateCheck: {
          branch: "main",
          current_sha: "old1111",
          current_version: "1.0.0",
          tracked_ref: "develop",
          tracked_ref_is_default: false,
          latest_sha: "tipsha7",
          latest_message: "feat(preview): things",
          latest_committed_at: "2026-05-22T10:00:00Z",
          latest_version: null,
          behind: true,
          changelog: [
            {
              title: "feat(preview): things",
              body: null,
              ref: "tipsha7abcdef",
              published_at: "2026-05-22T10:00:00Z",
              html_url: "https://example/commit/tipsha7",
            },
          ],
          reason: null,
        },
      }),
    );

    renderWithProviders(<MaintenancePanel />);

    // "preview · develop" badge marks non-default tracking.
    await screen.findByText(/preview · develop/i);
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

  it("renders the maintenance status as a cased label, not the raw token", async () => {
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

    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.queryByText("completed")).not.toBeInTheDocument();
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

  it("renders '—' with no expand toggle for a completed job with null result and null error", async () => {
    const nextId = { value: 2 };
    const jobs: Job[] = [
      {
        id: 1,
        kind: "rename_chapters",
        status: "completed",
        created_at: "2025-01-01T00:00:00",
        started_at: "2025-01-01T00:00:01",
        finished_at: "2025-01-01T00:00:02",
        result: null,
        error: null,
      },
    ];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {
      1: { status: "completed", total: 1, done: 1, lines: ["done"] },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    await screen.findByText("rename_chapters");
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /expand result/i }),
    ).not.toBeInTheDocument();
  });

  it("expand-result toggle stopPropagation: clicking expand on a non-selected row does not change selected log", async () => {
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
        error: "some error on job 2",
      },
      {
        id: 1,
        kind: "rename_chapters",
        status: "completed",
        created_at: "2025-01-01T00:00:00",
        started_at: "2025-01-01T00:00:01",
        finished_at: "2025-01-01T00:00:02",
        result: { renamed: 3 },
        error: null,
      },
    ];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {
      2: { status: "running", total: 5, done: 1, lines: ["working"] },
      1: { status: "completed", total: 3, done: 3, lines: ["done"] },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    // Auto-selected log is for job 2 (most recent).
    await screen.findByText(/Job #2/);

    // Expand the result cell on job 1 (non-selected row).
    const expandJob1 = screen.getByRole("button", {
      name: /expand result for maintenance job 1/i,
    });
    fireEvent.click(expandJob1);

    // The log header should still show Job #2 — stopPropagation prevented row selection.
    expect(screen.getByText(/Job #2/)).toBeInTheDocument();
    expect(screen.queryByText(/Job #1/)).not.toBeInTheDocument();
  });

  it("keeps the result payload collapsed by default and expands it inline on tap", async () => {
    const nextId = { value: 2 };
    const jobs: Job[] = [
      {
        id: 1,
        kind: "rename_chapters",
        status: "completed",
        created_at: "2025-01-01T00:00:00",
        started_at: "2025-01-01T00:00:01",
        finished_at: "2025-01-01T00:00:02",
        result: { renamed: 7 },
        error: null,
      },
    ];
    const progress: Record<
      number,
      { status: string; total: number; done: number; lines: string[] }
    > = {
      1: { status: "completed", total: 7, done: 7, lines: ["done"] },
    };
    mockFetch(jobsHandler({ jobs, nextId, progress }));

    renderWithProviders(<MaintenancePanel />);

    const toggle = await screen.findByRole("button", {
      name: /expand result for maintenance job 1/i,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(/\{"renamed":7\}/)).toBeInTheDocument();
    expect(screen.queryByTestId("maint-result-full-1")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: /collapse result for maintenance job 1/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("maint-result-full-1")).toHaveTextContent('{"renamed":7}');

    fireEvent.click(screen.getByRole("button", { name: /collapse result for maintenance job 1/i }));
    expect(
      screen.getByRole("button", { name: /expand result for maintenance job 1/i }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("maint-result-full-1")).not.toBeInTheDocument();
  });
});
