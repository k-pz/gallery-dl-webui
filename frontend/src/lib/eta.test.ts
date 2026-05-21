import { describe, expect, it } from "vitest";
import { computeEta, formatEta, parseStartedAt, recordSample } from "./eta";

describe("formatEta", () => {
  it("formats sub-minute durations in seconds", () => {
    expect(formatEta(0)).toBe("1s");
    expect(formatEta(1500)).toBe("2s");
    expect(formatEta(45_000)).toBe("45s");
  });

  it("rounds to minutes from one minute up", () => {
    expect(formatEta(60_000)).toBe("1m");
    expect(formatEta(8 * 60_000 + 20_000)).toBe("8m");
    expect(formatEta(59 * 60_000)).toBe("59m");
  });

  it("combines hours and minutes under a day", () => {
    expect(formatEta(60 * 60_000)).toBe("1h");
    expect(formatEta(2 * 60 * 60_000 + 15 * 60_000)).toBe("2h 15m");
  });

  it("collapses long durations to days", () => {
    expect(formatEta(24 * 60 * 60_000)).toBe("1d");
    expect(formatEta(3 * 24 * 60 * 60_000)).toBe("3d");
  });

  it("returns em-dash for invalid input", () => {
    expect(formatEta(Number.NaN)).toBe("—");
    expect(formatEta(-1000)).toBe("—");
    expect(formatEta(Number.POSITIVE_INFINITY)).toBe("—");
  });
});

describe("computeEta", () => {
  const base = { now: 100_000, startedAtMs: null as number | null };

  it("returns none when total is unknown", () => {
    expect(
      computeEta({ ...base, samples: [{ t: 90_000, done: 5 }], done: 5, total: null }),
    ).toEqual({ kind: "none" });
  });

  it("returns none before any progress", () => {
    expect(computeEta({ ...base, samples: [{ t: 90_000, done: 0 }], done: 0, total: 100 })).toEqual(
      { kind: "none" },
    );
  });

  it("returns none once done meets total", () => {
    expect(
      computeEta({ ...base, samples: [{ t: 90_000, done: 100 }], done: 100, total: 100 }),
    ).toEqual({ kind: "none" });
  });

  it("derives remaining time from the rolling window", () => {
    // 5 items in 10s = 0.5/s. 50 remaining → 100_000ms.
    const r = computeEta({
      now: 100_000,
      samples: [{ t: 90_000, done: 45 }],
      done: 50,
      total: 100,
      startedAtMs: null,
    });
    expect(r).toEqual({ kind: "eta", remainingMs: 100_000 });
  });

  it("falls back to cumulative when the rolling window shows no progress", () => {
    // Single sample with same done as current → rolling can't compute a rate.
    // Cumulative: 20 items in 100s = 0.2/s. 80 remaining → 400_000ms.
    const r = computeEta({
      now: 100_000,
      samples: [{ t: 99_000, done: 20 }],
      done: 20,
      total: 100,
      startedAtMs: 0,
    });
    expect(r).toEqual({ kind: "eta", remainingMs: 400_000 });
  });

  it("returns none when no rate is available", () => {
    // No cumulative anchor and no rolling delta.
    expect(
      computeEta({
        now: 100_000,
        samples: [{ t: 99_000, done: 10 }],
        done: 10,
        total: 100,
        startedAtMs: null,
      }),
    ).toEqual({ kind: "none" });
  });
});

describe("recordSample", () => {
  it("appends when done advances", () => {
    const s1 = recordSample([], 0, 0);
    expect(s1).toEqual([{ t: 0, done: 0 }]);
    const s2 = recordSample(s1, 1000, 5);
    expect(s2).toEqual([
      { t: 0, done: 0 },
      { t: 1000, done: 5 },
    ]);
  });

  it("skips unchanged samples", () => {
    const s1 = recordSample([{ t: 0, done: 5 }], 1000, 5);
    expect(s1).toEqual([{ t: 0, done: 5 }]);
  });

  it("drops samples that fell out of the window", () => {
    const samples = [
      { t: 0, done: 0 },
      { t: 10_000, done: 1 },
      { t: 30_000, done: 2 },
    ];
    const next = recordSample(samples, 70_000, 3, 60_000);
    expect(next[0]).toEqual({ t: 10_000, done: 1 });
    expect(next[next.length - 1]).toEqual({ t: 70_000, done: 3 });
  });

  it("always retains at least one sample", () => {
    const next = recordSample([{ t: 0, done: 5 }], 600_000, 5, 60_000);
    expect(next).toEqual([{ t: 0, done: 5 }]);
  });
});

describe("parseStartedAt", () => {
  it("parses ISO timestamps", () => {
    expect(parseStartedAt("2026-05-21T12:00:00Z")).toBe(Date.UTC(2026, 4, 21, 12));
  });

  it("returns null for nullish or invalid input", () => {
    expect(parseStartedAt(null)).toBeNull();
    expect(parseStartedAt(undefined)).toBeNull();
    expect(parseStartedAt("not-a-date")).toBeNull();
  });
});
