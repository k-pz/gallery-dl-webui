import { type RefObject, useEffect, useRef } from "react";

const FOCUSABLE = [
  "a[href]",
  'button:not([disabled]):not([tabindex="-1"])',
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/**
 * Focus management for aria-modal surfaces (nav drawer, jobs bottom sheet):
 * while `active`, focus moves inside the root, Tab wraps within it, Escape
 * calls `onClose`, and on deactivate focus returns to the element that had
 * it when the trap engaged. `lockScroll` additionally freezes body scroll —
 * pair it with any overlay that covers the page.
 */
export function useModalFocusTrap({
  active,
  rootRef,
  initialFocusRef,
  onClose,
  lockScroll = false,
}: {
  active: boolean;
  rootRef: RefObject<HTMLElement | null>;
  /** Focused on engage; falls back to the first focusable inside the root. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
  lockScroll?: boolean;
}) {
  // Read the latest callback through a ref so an inline `onClose` arrow
  // doesn't re-arm the trap (and re-steal focus) on every parent render.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!active) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusables = () =>
      Array.from(rootRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    (initialFocusRef?.current ?? focusables()[0])?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const els = focusables();
      if (els.length === 0) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);

    let restoreScroll: (() => void) | undefined;
    if (lockScroll) {
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      restoreScroll = () => {
        document.body.style.overflow = prev;
      };
    }
    return () => {
      document.removeEventListener("keydown", onKey);
      restoreScroll?.();
      opener?.focus();
    };
  }, [active, rootRef, initialFocusRef, lockScroll]);
}
