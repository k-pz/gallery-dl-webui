import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { findCall, jsonResponse, methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { DirectoryPicker } from "./DirectoryPicker";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DirectoryPicker create validation", () => {
  it("shows a sentence-case error on blank folder name and skips the request", async () => {
    const spy = mockFetch(async (input) => {
      if (urlOf(input).includes("/api/output-dirs")) return jsonResponse([]);
      return jsonResponse({});
    });

    renderWithProviders(
      <DirectoryPicker label="Output directory" value={null} onChange={() => {}} enabled />,
    );

    await userEvent.click(screen.getByRole("button", { name: /new folder/i }));
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText(/enter a folder name\./i)).toBeInTheDocument();
    expect(findCall(spy, (i, init) => methodOf(i, init) === "POST")).toBeUndefined();
  });
});
