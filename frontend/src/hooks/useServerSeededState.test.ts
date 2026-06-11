import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useServerSeededState } from "./useServerSeededState";

function run(initial: string) {
  return renderHook(({ server }: { server: string }) => useServerSeededState(server), {
    initialProps: { server: initial },
  });
}

describe("useServerSeededState", () => {
  it("seeds from the server value and follows refetches while untouched", () => {
    const { result, rerender } = run("");
    expect(result.current.value).toBe("");
    expect(result.current.dirty).toBe(false);

    rerender({ server: "v1.0" });
    expect(result.current.value).toBe("v1.0");
  });

  it("stops re-seeding once the user edits", () => {
    const { result, rerender } = run("v1.0");
    act(() => result.current.setValue("v2.0-draft"));
    expect(result.current.dirty).toBe(true);

    rerender({ server: "v1.1" });
    expect(result.current.value).toBe("v2.0-draft");
  });

  it("resumes seeding after markClean", () => {
    const { result, rerender } = run("v1.0");
    act(() => result.current.setValue("v2.0"));
    act(() => result.current.markClean());
    expect(result.current.dirty).toBe(false);

    // markClean alone re-seeds from the current server value…
    expect(result.current.value).toBe("v1.0");
    // …and later refetches keep flowing through.
    rerender({ server: "v2.0" });
    expect(result.current.value).toBe("v2.0");
  });

  it("overwrite changes the value without marking it dirty", () => {
    const { result, rerender } = run("v1.0");
    act(() => result.current.overwrite(""));
    expect(result.current.value).toBe("");
    expect(result.current.dirty).toBe(false);

    rerender({ server: "v1.1" });
    expect(result.current.value).toBe("v1.1");
  });

  it("overwrite preserves dirtiness from an earlier edit", () => {
    const { result, rerender } = run("v1.0");
    act(() => result.current.setValue("typed"));
    act(() => result.current.overwrite(""));
    expect(result.current.dirty).toBe(true);

    rerender({ server: "v1.1" });
    expect(result.current.value).toBe("");
  });
});
