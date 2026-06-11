import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "../test/render";
import { ThemeToggle } from "./ThemeToggle";

beforeEach(() => {
  window.localStorage.clear();
});

describe("ThemeToggle", () => {
  it("cycles system → light → dark → system", () => {
    renderWithProviders(<ThemeToggle />);

    const button = () => screen.getByRole("button");
    expect(button()).toHaveAccessibleName("Theme: system — switch to light");

    fireEvent.click(button());
    expect(button()).toHaveAccessibleName("Theme: light — switch to dark");

    fireEvent.click(button());
    expect(button()).toHaveAccessibleName("Theme: dark — switch to system");

    fireEvent.click(button());
    expect(button()).toHaveAccessibleName("Theme: system — switch to light");
  });
});
