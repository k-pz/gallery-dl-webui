import type { ReactNode } from "react";
import { useEffect } from "react";
import { IconActivity, IconFileText, IconLibrary, IconSliders, IconWrench, IconX } from "./Icons";

type NavKey = "library" | "jobs" | "config" | "maintenance" | "logs";

const NAV_ITEMS: { key: NavKey; label: string; icon: ReactNode }[] = [
  { key: "library", label: "Library", icon: <IconLibrary size={20} /> },
  { key: "jobs", label: "Jobs", icon: <IconActivity size={20} /> },
  { key: "config", label: "Config", icon: <IconSliders size={20} /> },
  { key: "maintenance", label: "Maintain", icon: <IconWrench size={20} /> },
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
  // Close on Escape and lock body scroll while open. Both are cleaned up when
  // the drawer hides so we don't leak listeners or freeze the page.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  return (
    <div className="mob-drawer-root" data-open={open} aria-hidden={!open}>
      <button
        type="button"
        className="mob-drawer-scrim"
        tabIndex={open ? 0 : -1}
        aria-label="Close menu"
        onClick={onClose}
      />
      <aside className="mob-drawer" role="dialog" aria-modal="true" aria-label="Primary navigation">
        <div className="mob-drawer-head">
          <span className="mob-drawer-title">Navigate</span>
          <button
            type="button"
            className="mob-drawer-close"
            aria-label="Close menu"
            onClick={onClose}
            tabIndex={open ? 0 : -1}
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
