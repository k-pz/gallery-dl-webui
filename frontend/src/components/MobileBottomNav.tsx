import type { ReactNode } from "react";
import { IconActivity, IconFileText, IconLibrary, IconSliders, IconWrench } from "./Icons";

type NavKey = "library" | "jobs" | "config" | "maintenance" | "logs";

const NAV_ITEMS: { key: NavKey; label: string; icon: ReactNode }[] = [
  { key: "library", label: "Library", icon: <IconLibrary size={20} /> },
  { key: "jobs", label: "Jobs", icon: <IconActivity size={20} /> },
  { key: "config", label: "Config", icon: <IconSliders size={20} /> },
  { key: "maintenance", label: "Maintain", icon: <IconWrench size={20} /> },
  { key: "logs", label: "Logs", icon: <IconFileText size={20} /> },
];

/**
 * Bottom navigation for phones. Hidden on >=768px via `.mob-nav` CSS.
 *
 * `jobsBadge` shows the live running count on the Jobs item — kept in sync
 * with the same value that drives the desktop tab badge.
 */
export function MobileBottomNav({
  active,
  jobsBadge,
  onChange,
}: {
  active: string | null;
  jobsBadge?: number;
  onChange: (key: NavKey) => void;
}) {
  return (
    <nav className="mob-nav" aria-label="Primary">
      {NAV_ITEMS.map((it) => (
        <button
          key={it.key}
          type="button"
          className="mob-nav-item"
          data-active={active === it.key}
          aria-current={active === it.key ? "page" : undefined}
          onClick={() => onChange(it.key)}
        >
          {it.icon}
          <span>{it.label}</span>
          {it.key === "jobs" && jobsBadge && jobsBadge > 0 ? (
            // The visible "2" is read out as part of the parent button's
            // accessible name ("Jobs 2"); no extra aria needed on the span.
            <span className="mob-nav-badge">{jobsBadge}</span>
          ) : null}
        </button>
      ))}
    </nav>
  );
}
