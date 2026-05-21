import { describe, expect, it } from "vitest";
import { SERIES_STATUS_OPTIONS, SERIES_STATUS_VALUES, seriesStatusTone } from "./seriesStatus";

describe("seriesStatusTone", () => {
  it("maps each Komga status to a pill tone", () => {
    expect(seriesStatusTone("Ongoing")).toBe("active");
    expect(seriesStatusTone("Ended")).toBe("done");
    expect(seriesStatusTone("Hiatus")).toBe("warn");
    expect(seriesStatusTone("Abandoned")).toBe("error");
  });

  it("returns undefined for blank/null inputs (suppresses the pill entirely)", () => {
    expect(seriesStatusTone(null)).toBeUndefined();
    expect(seriesStatusTone(undefined)).toBeUndefined();
    expect(seriesStatusTone("")).toBeUndefined();
  });

  it("falls back to muted for unrecognised non-empty values", () => {
    expect(seriesStatusTone("Publishing")).toBe("muted");
  });
});

describe("SERIES_STATUS_OPTIONS", () => {
  it("matches the canonical Komga set the backend writes to series.json", () => {
    expect(SERIES_STATUS_VALUES).toEqual(["Ongoing", "Ended", "Hiatus", "Abandoned"]);
    for (const opt of SERIES_STATUS_OPTIONS) {
      expect(opt.value).toBe(opt.label);
    }
  });
});
