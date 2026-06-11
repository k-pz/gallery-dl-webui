import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useAutoSelectJob } from "./useAutoSelectJob";

type Job = { id: number; status: string };

function run(initial: Job[] | undefined, initialId: number | null = null) {
  return renderHook(
    ({ downloads }: { downloads: Job[] | undefined }) => useAutoSelectJob(downloads, initialId),
    {
      initialProps: { downloads: initial },
    },
  );
}

describe("useAutoSelectJob", () => {
  it("auto-opens the current running job", () => {
    const { result } = run([
      { id: 1, status: "completed" },
      { id: 2, status: "running" },
    ]);
    expect(result.current.selectedId).toBe(2);
  });

  it("advances to the next active job when the auto-opened one finishes", () => {
    const { result, rerender } = run([
      { id: 2, status: "running" },
      { id: 3, status: "pending" },
    ]);
    expect(result.current.selectedId).toBe(2);

    rerender({
      downloads: [
        { id: 2, status: "completed" },
        { id: 3, status: "running" },
      ],
    });
    expect(result.current.selectedId).toBe(3);
  });

  it("does not advance away from a manual pick", () => {
    const { result, rerender } = run([
      { id: 2, status: "running" },
      { id: 3, status: "pending" },
    ]);
    act(() => result.current.selectJob(5));
    expect(result.current.selectedId).toBe(5);

    rerender({
      downloads: [
        { id: 2, status: "running" },
        { id: 3, status: "pending" },
        { id: 5, status: "completed" },
      ],
    });
    expect(result.current.selectedId).toBe(5);
  });

  it("does not hijack a manual re-pick of the last auto-selected job", () => {
    const { result, rerender } = run([{ id: 2, status: "running" }]);
    expect(result.current.selectedId).toBe(2);

    // The user re-selects the same job by hand; once it finishes with other
    // jobs still active, the view must stay put.
    act(() => result.current.selectJob(2));
    rerender({
      downloads: [
        { id: 2, status: "completed" },
        { id: 3, status: "running" },
      ],
    });
    expect(result.current.selectedId).toBe(2);
  });

  it("respects an explicit close", () => {
    const { result, rerender } = run([{ id: 2, status: "running" }]);
    expect(result.current.selectedId).toBe(2);

    act(() => result.current.selectJob(null));
    expect(result.current.selectedId).toBeNull();

    // Even with active jobs around, no auto re-open after a close.
    rerender({ downloads: [{ id: 2, status: "running" }] });
    expect(result.current.selectedId).toBeNull();
  });

  it("does nothing while the list is empty or undefined", () => {
    const { result, rerender } = run(undefined);
    expect(result.current.selectedId).toBeNull();
    rerender({ downloads: [] });
    expect(result.current.selectedId).toBeNull();
  });

  it("treats an initial deep-linked id as a manual pick", () => {
    const { result, rerender } = run(
      [
        { id: 2, status: "running" },
        { id: 5, status: "completed" },
      ],
      5,
    );
    // No auto-open over the restored selection…
    expect(result.current.selectedId).toBe(5);
    expect(result.current.isManualSelection).toBe(true);

    // …and no auto-advance away from it, even though it is terminal.
    rerender({
      downloads: [
        { id: 2, status: "running" },
        { id: 5, status: "completed" },
      ],
    });
    expect(result.current.selectedId).toBe(5);
  });

  it("flags auto-opened selections as not manual", () => {
    const { result } = run([{ id: 2, status: "running" }]);
    expect(result.current.selectedId).toBe(2);
    expect(result.current.isManualSelection).toBe(false);

    act(() => result.current.selectJob(2));
    expect(result.current.isManualSelection).toBe(true);

    act(() => result.current.selectJob(null));
    expect(result.current.isManualSelection).toBe(false);
  });
});
