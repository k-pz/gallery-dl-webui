import { describe, expect, it } from "vitest";
import { isTerminal, statusColor } from "./status";

describe("statusColor", () => {
  it("maps each known status to its color", () => {
    expect(statusColor("pending")).toBe("gray");
    expect(statusColor("extracting")).toBe("yellow");
    expect(statusColor("running")).toBe("blue");
    expect(statusColor("completed")).toBe("green");
    expect(statusColor("failed")).toBe("red");
  });

  it("falls back to gray for unknown statuses", () => {
    expect(statusColor("anything-else")).toBe("gray");
    expect(statusColor("")).toBe("gray");
  });
});

describe("isTerminal", () => {
  it("returns true only for completed and failed", () => {
    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
  });

  it("returns false for in-progress statuses", () => {
    expect(isTerminal("pending")).toBe(false);
    expect(isTerminal("extracting")).toBe(false);
    expect(isTerminal("running")).toBe(false);
  });
});
