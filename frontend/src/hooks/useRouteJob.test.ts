import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { initialJobIdFromUrl, useSyncJobParam } from "./useRouteJob";
import type { Tab } from "./useRouteTab";

afterEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("initialJobIdFromUrl", () => {
  it("parses a positive integer on the jobs tab", () => {
    window.history.replaceState({}, "", "/jobs?job=123");
    expect(initialJobIdFromUrl()).toBe(123);
  });

  it("ignores the param outside the jobs tab", () => {
    window.history.replaceState({}, "", "/library?job=123");
    expect(initialJobIdFromUrl()).toBeNull();
  });

  it("rejects malformed or non-positive values", () => {
    for (const bad of ["abc", "-3", "0", "1.5", ""]) {
      window.history.replaceState({}, "", `/jobs?job=${bad}`);
      expect(initialJobIdFromUrl()).toBeNull();
    }
    window.history.replaceState({}, "", "/jobs");
    expect(initialJobIdFromUrl()).toBeNull();
  });
});

describe("useSyncJobParam", () => {
  function run(tab: Tab, jobId: number | null) {
    return renderHook(({ t, id }: { t: Tab; id: number | null }) => useSyncJobParam(t, id), {
      initialProps: { t: tab, id: jobId },
    });
  }

  it("writes the param on the jobs tab and clears it on close", () => {
    window.history.replaceState({}, "", "/jobs");
    const { rerender } = run("jobs", 7);
    expect(window.location.search).toBe("?job=7");

    rerender({ t: "jobs", id: null });
    expect(window.location.search).toBe("");
  });

  it("drops the param when leaving the jobs tab and restores it on return", () => {
    window.history.replaceState({}, "", "/jobs?job=7");
    const { rerender } = run("jobs", 7);

    window.history.replaceState({}, "", "/config?job=7");
    rerender({ t: "config", id: 7 });
    expect(window.location.search).toBe("");

    window.history.replaceState({}, "", "/jobs");
    rerender({ t: "jobs", id: 7 });
    expect(window.location.search).toBe("?job=7");
  });

  it("replaces instead of pushing history entries", () => {
    window.history.replaceState({}, "", "/jobs");
    const before = window.history.length;
    const { rerender } = run("jobs", 1);
    rerender({ t: "jobs", id: 2 });
    rerender({ t: "jobs", id: 3 });
    expect(window.history.length).toBe(before);
  });
});
