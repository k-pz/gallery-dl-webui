import { describe, expect, it } from "vitest";
import { chapterStageLabel, isTerminal, jobStatusLabel, jobStep, statusColor } from "./status";

describe("statusColor", () => {
  it("maps each known status to its color", () => {
    expect(statusColor("pending")).toBe("gray");
    expect(statusColor("extracting")).toBe("yellow");
    expect(statusColor("running")).toBe("blue");
    expect(statusColor("completed")).toBe("green");
    expect(statusColor("failed")).toBe("red");
    expect(statusColor("cancelled")).toBe("orange");
    expect(statusColor("cancelling")).toBe("orange");
  });

  it("falls back to gray for unknown statuses", () => {
    expect(statusColor("anything-else")).toBe("gray");
    expect(statusColor("")).toBe("gray");
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

describe("chapterStageLabel", () => {
  it("maps chapter stage names to title case labels", () => {
    expect(chapterStageLabel("downloading")).toBe("Downloading");
    expect(chapterStageLabel("downloaded")).toBe("Downloaded");
    expect(chapterStageLabel("processing")).toBe("Processing");
    expect(chapterStageLabel("completed")).toBe("Completed");
  });
});
