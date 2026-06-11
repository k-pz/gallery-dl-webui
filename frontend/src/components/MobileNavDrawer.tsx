import type { ReactNode } from "react";
import { useRef } from "react";
import { useModalFocusTrap } from "../hooks/useModalFocusTrap";
import {
  ICON_SIZE,
  IconActivity,
  IconFileText,
  IconLibrary,
  IconSliders,
  IconWrench,
  IconX,
} from "./Icons";

type NavKey = "library" | "jobs" | "config" | "maintenance" | "logs";

const NAV_ITEMS: { key: NavKey; label: string; icon: ReactNode }[] = [
  { key: "library", label: "Library", icon: <IconLibrary size={ICON_SIZE.xl} /> },
  { key: "jobs", label: "Jobs", icon: <IconActivity size={ICON_SIZE.xl} /> },
  { key: "config", label: "Config", icon: <IconSliders size={ICON_SIZE.xl} /> },
  { key: "maintenance", label: "Maintenance", icon: <IconWrench size={ICON_SIZE.xl} /> },
  { key: "logs", label: "Logs", icon: <IconFileText size={ICON_SIZE.xl} /> },
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

  // The dialog is aria-modal: focus moves to the close button on open, Tab
  // wraps inside, Escape closes, body scroll locks, and focus returns to
  // the opener on close (shared trap — see useModalFocusTrap).
  useModalFocusTrap({
    active: open,
    rootRef,
    initialFocusRef: closeBtnRef,
    onClose,
    lockScroll: true,
  });

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
            <IconX size={ICON_SIZE.lg} />
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
