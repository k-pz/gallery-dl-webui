import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useRouteTab } from "./useRouteTab";

afterEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("useRouteTab", () => {
  it("derives the initial tab from the pathname", () => {
    window.history.replaceState({}, "", "/jobs");
    const { result } = renderHook(() => useRouteTab());
    expect(result.current[0]).toBe("jobs");
  });

  it("falls back to library on unknown paths", () => {
    window.history.replaceState({}, "", "/no-such-tab");
    const { result } = renderHook(() => useRouteTab());
    expect(result.current[0]).toBe("library");
  });

  it("setTab pushes the path and ignores invalid values", () => {
    window.history.replaceState({}, "", "/");
    const { result } = renderHook(() => useRouteTab());
    act(() => result.current[1]("config"));
    expect(result.current[0]).toBe("config");
    expect(window.location.pathname).toBe("/config");

    act(() => result.current[1]("not-a-tab"));
    expect(result.current[0]).toBe("config");
    expect(window.location.pathname).toBe("/config");
  });

  it("follows browser back/forward via popstate", () => {
    window.history.replaceState({}, "", "/library");
    const { result } = renderHook(() => useRouteTab());
    act(() => result.current[1]("logs"));
    expect(result.current[0]).toBe("logs");

    // jsdom's history.back() is async-ish; simulate the popstate directly.
    act(() => {
      window.history.replaceState({}, "", "/library");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(result.current[0]).toBe("library");
  });
});
