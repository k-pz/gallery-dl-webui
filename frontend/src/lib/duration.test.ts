import { describe, expect, it } from "vitest";
import { isValidDuration } from "./duration";

describe("isValidDuration", () => {
  it("accepts the formats the backend accepts", () => {
    for (const ok of ["30s", "5m", "2h", "1d", "1w", "2h30m", "1w2d3h", " 1d 12h ", "1D"]) {
      expect(isValidDuration(ok), ok).toBe(true);
    }
  });

  it("rejects what the backend rejects", () => {
    for (const bad of ["", "60", "1x", "h", "1.5h", "-1d", "0m", "0h0m", "1d foo"]) {
      expect(isValidDuration(bad), bad).toBe(false);
    }
  });
});
