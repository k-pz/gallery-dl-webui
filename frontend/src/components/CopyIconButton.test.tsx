import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { CopyIconButton } from "./CopyIconButton";

describe("CopyIconButton", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("copies via navigator.clipboard and flashes the copied state", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    renderWithProviders(<CopyIconButton value="https://example.com/x" label="Copy URL" />);
    const btn = screen.getByRole("button", { name: "Copy URL" });

    await act(async () => {
      fireEvent.click(btn);
    });
    expect(writeText).toHaveBeenCalledWith("https://example.com/x");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("button", { name: "Copy URL" })).toBeInTheDocument();
  });

  it("falls back to execCommand when the clipboard API is unavailable", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    const exec = vi.fn().mockReturnValue(true);
    document.execCommand = exec as unknown as typeof document.execCommand;

    renderWithProviders(<CopyIconButton value="plain-http" label="Copy URL" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy URL" }));
    });
    expect(exec).toHaveBeenCalledWith("copy");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });
});
