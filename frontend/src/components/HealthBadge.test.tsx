import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { HealthBadge } from "./HealthBadge";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HealthBadge", () => {
  it("reads 'checking' while the health query is loading", () => {
    mockFetch(() => new Promise<Response>(() => {}));
    renderWithProviders(<HealthBadge />);
    expect(screen.getByText("checking")).toBeInTheDocument();
  });

  it("reads the backend status once loaded", async () => {
    mockFetch(async (input) => {
      if (urlOf(input).includes("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse({});
    });
    renderWithProviders(<HealthBadge />);
    expect(await screen.findByText("ok")).toBeInTheDocument();
  });
});
