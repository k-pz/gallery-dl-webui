import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { IconActivity, IconFileText, IconLibrary, IconSliders, IconWrench, IconX } from "./Icons";

type NavKey = "library" | "jobs" | "config" | "maintenance" | "logs";

const NAV_ITEMS: { key: NavKey; label: string; icon: ReactNode }[] = [
  { key: "library", label: "Library", icon: <IconLibrary size={20} /> },
  { key: "jobs", label: "Jobs", icon: <IconActivity size={20} /> },
  { key: "config", label: "Config", icon: <IconSliders size={20} /> },
  { key: "maintenance", label: "Maintenance", icon: <IconWrench size={20} /> },
  { key: "logs", label: "Logs", icon: <IconFileText size={20} /> },
];

/**
 * Right-side slide-in navigation for phones. Replaces the previous bottom
 * tab strip, which fought a losing battle against Firefox iOS painting page
 * content in the band the URL pill exposes on scroll. Header chrome stays
 * predictable and the page can scroll to its real bottom.
 */
export function MobileNavDrawer({
  active,
  open,
  jobsBadge,
  onChange,
  onClose,
}: {
  active: string | null;
  open: boolean;
  jobsBadge?: number;
  onChange: (key: NavKey) => void;
  onClose: () => void;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);

  // Close on Escape, lock body scroll, and manage focus while open: the
  // dialog is aria-modal, so focus must move into it on open, stay trapped
  // inside (Tab wraps), and return to the opener on close. All cleaned up
  // when the drawer hides so we don't leak listeners or freeze the page.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeBtnRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const root = rootRef.current;
      if (!root) return;
      const focusables = Array.from(
        root.querySelectorAll<HTMLElement>("button:not([tabindex='-1'])"),
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      opener?.focus();
    };
  }, [open, onClose]);

  return (
    <div className="mob-drawer-root" data-open={open} aria-hidden={!open} ref={rootRef}>
      <button
        type="button"
        className="mob-drawer-scrim"
        tabIndex={open ? 0 : -1}
        aria-label="Close menu"
        onClick={onClose}
      />
      <aside className="mob-drawer" role="dialog" aria-modal="true" aria-label="Primary navigation">
        <div className="mob-drawer-head">
          <span className="mob-drawer-title">Sections</span>
          <button
            type="button"
            className="mob-drawer-close"
            aria-label="Close menu"
            onClick={onClose}
            tabIndex={open ? 0 : -1}
            ref={closeBtnRef}
          >
            <IconX size={18} />
          </button>
        </div>
        <nav className="mob-drawer-nav" aria-label="Primary">
          {NAV_ITEMS.map((it) => (
            <button
              key={it.key}
              type="button"
              className="mob-drawer-item"
              data-active={active === it.key}
              aria-current={active === it.key ? "page" : undefined}
              tabIndex={open ? 0 : -1}
              onClick={() => {
                onChange(it.key);
                onClose();
              }}
            >
              {it.icon}
              <span className="mob-drawer-item-label">{it.label}</span>
              {it.key === "jobs" && jobsBadge && jobsBadge > 0 ? (
                <span className="mob-drawer-item-badge">{jobsBadge}</span>
              ) : null}
            </button>
          ))}
        </nav>
        <div className="mob-drawer-foot">
          <span className="mob-drawer-foot-tag">archive</span>
        </div>
      </aside>
    </div>
  );
}
