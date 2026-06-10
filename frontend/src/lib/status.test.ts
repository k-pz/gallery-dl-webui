import { describe, expect, it } from "vitest";
import {
  chapterStageLabel,
  isTerminal,
  jobStatusLabel,
  jobStep,
  pickCurrentActiveJobId,
  statusTone,
} from "./status";

describe("chapter outcome presentation", () => {
  it("labels downloaded/skipped/failed chapter outcomes", () => {
    expect(chapterStageLabel("downloaded")).toBe("Downloaded");
    expect(chapterStageLabel("skipped")).toBe("Skipped");
    expect(chapterStageLabel("failed")).toBe("Failed");
  });

  it("tones failed as error and skipped as muted", () => {
    expect(statusTone("failed")).toBe("error");
    expect(statusTone("skipped")).toBe("muted");
    expect(statusTone("downloaded")).toBe("info");
  });
});

describe("isTerminal", () => {
  it("returns true for terminal statuses", () => {
    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("cancelled")).toBe(true);
  });

  it("returns false for in-progress statuses", () => {
    expect(isTerminal("pending")).toBe(false);
    expect(isTerminal("extracting")).toBe(false);
    expect(isTerminal("running")).toBe(false);
  });
});

describe("jobStatusLabel", () => {
  it("maps backend job states to lifecycle labels", () => {
    expect(jobStatusLabel("pending")).toBe("Scheduled");
    expect(jobStatusLabel("extracting")).toBe("Fetching metadata");
    expect(jobStatusLabel("running")).toBe("Downloading");
    expect(jobStatusLabel("completed")).toBe("Completed");
  });
});

describe("jobStep", () => {
  it("shows downloaded when files are done but postprocess has not started", () => {
    expect(jobStep("completed", null)).toMatchObject({ label: "Downloaded", index: 3 });
  });

  it("shows processing while postprocess is running", () => {
    expect(jobStep("completed", "running")).toMatchObject({ label: "Processing", index: 4 });
  });
});

describe("pickCurrentActiveJobId", () => {
  it("picks the oldest running job", () => {
    expect(
      pickCurrentActiveJobId([
        { id: 3, status: "running" },
        { id: 1, status: "running" },
        { id: 2, status: "extracting" },
      ]),
    ).toBe(1);
  });

  it("falls back to the oldest pending job when nothing is running", () => {
    expect(
      pickCurrentActiveJobId([
        { id: 5, status: "completed" },
        { id: 7, status: "pending" },
        { id: 4, status: "pending" },
      ]),
    ).toBe(4);
  });

  it("prefers a running job over a pending one even when the pending id is smaller", () => {
    expect(
      pickCurrentActiveJobId([
        { id: 2, status: "pending" },
        { id: 9, status: "running" },
      ]),
    ).toBe(9);
  });

  it("returns null when no jobs are active", () => {
    expect(
      pickCurrentActiveJobId([
        { id: 1, status: "completed" },
        { id: 2, status: "failed" },
        { id: 3, status: "cancelled" },
      ]),
    ).toBeNull();
  });

  it("returns null for an empty list", () => {
    expect(pickCurrentActiveJobId([])).toBeNull();
  });
});

describe("chapterStageLabel", () => {
  it("maps chapter stage names to title case labels", () => {
    expect(chapterStageLabel("downloading")).toBe("Downloading");
    expect(chapterStageLabel("downloaded")).toBe("Downloaded");
    expect(chapterStageLabel("processing")).toBe("Processing");
    expect(chapterStageLabel("completed")).toBe("Completed");
  });
});
