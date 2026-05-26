import { describe, expect, it } from "vitest";
import {
  READING_DIRECTION_OPTIONS,
  READING_DIRECTION_VALUES,
  readingDirectionLabel,
} from "./readingDirection";

describe("READING_DIRECTION_OPTIONS", () => {
  it("exposes all four directions the backend recognises", () => {
    // The set is shared with backend's ReadingDirection enum; if you add a
    // value backend-side make sure the frontend stays in step.
    expect(READING_DIRECTION_VALUES).toEqual(["ltr", "rtl", "vertical", "webtoon"]);
  });

  it("pairs every value with a human label", () => {
    for (const option of READING_DIRECTION_OPTIONS) {
      expect(option.label.length).toBeGreaterThan(0);
    }
  });
});

describe("readingDirectionLabel", () => {
  it("returns the canonical label for known values", () => {
    expect(readingDirectionLabel("ltr")).toBe("Left to right");
    expect(readingDirectionLabel("rtl")).toBe("Right to left");
    expect(readingDirectionLabel("vertical")).toBe("Vertical");
    expect(readingDirectionLabel("webtoon")).toBe("Webtoon");
  });

  it("passes unknown non-empty values through as-is", () => {
    // Backends occasionally surface novel hints (e.g. from new manga
    // extractors); rendering them verbatim is preferable to silently
    // collapsing to the em-dash placeholder.
    expect(readingDirectionLabel("upside-down")).toBe("upside-down");
  });

  it("renders an em-dash for nullish or blank values", () => {
    expect(readingDirectionLabel(null)).toBe("—");
    expect(readingDirectionLabel(undefined)).toBe("—");
    expect(readingDirectionLabel("")).toBe("—");
  });
});
