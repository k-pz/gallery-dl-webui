import { describe, expect, it } from "vitest";
import { formatDate } from "./time";

describe("formatDate", () => {
  it("returns an em dash for missing values", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("")).toBe("—");
  });

  it("passes a bare year through untouched", () => {
    expect(formatDate("2019")).toBe("2019");
  });

  it("passes unparseable values through untouched", () => {
    expect(formatDate("unknown")).toBe("unknown");
  });

  it("formats a date-only string without shifting the calendar day", () => {
    // Date-only ISO strings parse as UTC midnight; rendering in local time
    // would show the previous day in timezones behind UTC.
    expect(formatDate("2019-05-01")).toBe(
      new Date(Date.UTC(2019, 4, 1)).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      }),
    );
  });
});
