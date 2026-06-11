import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { useModalFocusTrap } from "./useModalFocusTrap";

function Fixture({ onClose, lockScroll }: { onClose: () => void; lockScroll?: boolean }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  useModalFocusTrap({
    active: open,
    rootRef,
    onClose,
    lockScroll,
  });
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        opener
      </button>
      {open && (
        <div ref={rootRef}>
          <button type="button" onClick={() => setOpen(false)}>
            first
          </button>
          <button type="button">last</button>
        </div>
      )}
    </div>
  );
}

describe("useModalFocusTrap", () => {
  it("moves focus in on engage and back to the opener on close", () => {
    render(<Fixture onClose={() => {}} />);
    const opener = screen.getByRole("button", { name: "opener" });
    opener.focus();
    fireEvent.click(opener);
    expect(screen.getByRole("button", { name: "first" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "first" }));
    expect(opener).toHaveFocus();
  });

  it("wraps Tab and Shift+Tab at the edges", () => {
    render(<Fixture onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "opener" }));
    const first = screen.getByRole("button", { name: "first" });
    const last = screen.getByRole("button", { name: "last" });

    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("calls onClose on Escape", () => {
    const onClose = vi.fn();
    render(<Fixture onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "opener" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("locks and restores body scroll when asked", () => {
    render(<Fixture onClose={() => {}} lockScroll />);
    expect(document.body.style.overflow).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "opener" }));
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "first" }));
    expect(document.body.style.overflow).toBe("");
  });
});
