import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";

const importLibrary = vi.fn();
vi.mock("../lib/libraryBackup", () => ({
  exportLibrary: vi.fn(),
  importLibrary: (...args: unknown[]) => importLibrary(...args),
}));
vi.mock("../lib/invalidate", () => ({
  useDataInvalidators: () => ({ targets: vi.fn() }),
}));

import { LibraryBackup } from "./LibraryBackup";

afterEach(() => {
  vi.clearAllMocks();
});

describe("LibraryBackup import errors", () => {
  it("renders every import error inside a capped scroll container", async () => {
    const errors = Array.from({ length: 40 }, (_, i) => `row ${i} failed: bad url`);
    importLibrary.mockResolvedValue({ imported: 1, updated: 0, errors });

    const { container } = renderWithProviders(<LibraryBackup />);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "lib.yaml", { type: "text/yaml" }));

    await waitFor(() =>
      expect(screen.getByText(/40 series could not be imported/i)).toBeInTheDocument(),
    );

    expect(screen.getByText("row 0 failed: bad url")).toBeInTheDocument();
    expect(screen.getByText("row 39 failed: bad url")).toBeInTheDocument();
    expect(container.querySelector(".mantine-ScrollArea-viewport")).not.toBeNull();
  });
});
