import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useOptimisticCancel, useOptimisticCancelMany } from "./optimisticCancel";

describe("useOptimisticCancel", () => {
  it("flags cancelling between mark() and the job going terminal", () => {
    const { result, rerender } = renderHook(
      ({ id, status }: { id: number; status: string }) => useOptimisticCancel(id, status),
      { initialProps: { id: 1, status: "running" } },
    );
    expect(result.current.cancelling).toBe(false);

    act(() => result.current.mark());
    expect(result.current.cancelling).toBe(true);

    // Backend reflects the cancel — the flag auto-clears.
    rerender({ id: 1, status: "cancelled" });
    expect(result.current.cancelling).toBe(false);
  });

  it("resets when the focused job changes", () => {
    const { result, rerender } = renderHook(
      ({ id, status }: { id: number; status: string }) => useOptimisticCancel(id, status),
      { initialProps: { id: 1, status: "running" } },
    );
    act(() => result.current.mark());
    expect(result.current.cancelling).toBe(true);

    rerender({ id: 2, status: "running" });
    expect(result.current.cancelling).toBe(false);
  });

  it("clear() drops the flag (cancel request failed)", () => {
    const { result } = renderHook(() => useOptimisticCancel(1, "running"));
    act(() => result.current.mark());
    act(() => result.current.clear());
    expect(result.current.cancelling).toBe(false);
  });
});

describe("useOptimisticCancelMany", () => {
  it("tracks per-id flags and auto-prunes terminal items", () => {
    const { result, rerender } = renderHook(
      ({ items }: { items: { id: number; status: string }[] }) => useOptimisticCancelMany(items),
      {
        initialProps: {
          items: [
            { id: 1, status: "running" },
            { id: 2, status: "running" },
          ],
        },
      },
    );
    act(() => result.current.mark(1));
    expect(result.current.isCancelling(1)).toBe(true);
    expect(result.current.isCancelling(2)).toBe(false);

    // Item 1 goes terminal — the flag is pruned on the next items update.
    rerender({
      items: [
        { id: 1, status: "cancelled" },
        { id: 2, status: "running" },
      ],
    });
    expect(result.current.isCancelling(1)).toBe(false);
  });

  it("prunes flags for items that disappear from the list", () => {
    const { result, rerender } = renderHook(
      ({ items }: { items: { id: number; status: string }[] }) => useOptimisticCancelMany(items),
      { initialProps: { items: [{ id: 5, status: "pending" }] } },
    );
    act(() => result.current.mark(5));
    rerender({ items: [] });
    expect(result.current.isCancelling(5)).toBe(false);
  });
});
