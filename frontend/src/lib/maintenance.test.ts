import { describe, expect, it } from "vitest";
import { maintStatusLabel } from "./maintenance";
import { jobStatusLabel } from "./status";

describe("maintStatusLabel", () => {
  it("maps pending to 'Queued' (not 'Scheduled' like jobStatusLabel)", () => {
    expect(maintStatusLabel("pending")).toBe("Queued");
    expect(jobStatusLabel("pending")).toBe("Scheduled");
    expect(maintStatusLabel("pending")).not.toBe(jobStatusLabel("pending"));
  });

  it("maps running to 'Running' (not 'Downloading' like jobStatusLabel)", () => {
    expect(maintStatusLabel("running")).toBe("Running");
    expect(jobStatusLabel("running")).toBe("Downloading");
    expect(maintStatusLabel("running")).not.toBe(jobStatusLabel("running"));
  });

  it("maps completed to 'Completed'", () => {
    expect(maintStatusLabel("completed")).toBe("Completed");
  });

  it("maps failed to 'Failed'", () => {
    expect(maintStatusLabel("failed")).toBe("Failed");
  });

  it("maps cancelled to 'Cancelled'", () => {
    expect(maintStatusLabel("cancelled")).toBe("Cancelled");
  });

  it("passes through unknown tokens unchanged", () => {
    expect(maintStatusLabel("weird")).toBe("weird");
  });
});
