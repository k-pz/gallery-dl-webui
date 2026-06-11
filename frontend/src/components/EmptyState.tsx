import type { ReactNode } from "react";
import { ICON_SIZE, IconArrowUp } from "./Icons";

/**
 * Glyph + title + body + secondary action. `arrow` adds a directional cue
 * pointing at the form above the empty state — used on the library tab to
 * say "type a URL up there".
 *
 * `compact` is the low-ceremony variant for transient emptiness (e.g. "no
 * rows match the filters"): same dashed treatment so all empty surfaces
 * read as one family, but smaller and glyph-less.
 */
export function EmptyState({
  icon,
  title,
  body,
  actions,
  arrow,
  compact,
}: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  actions?: ReactNode;
  arrow?: boolean;
  compact?: boolean;
}) {
  return (
    <div className="app-empty" data-compact={compact || undefined}>
      {arrow && (
        <div className="app-empty-arrow" aria-hidden="true">
          <IconArrowUp size={ICON_SIZE.lg} />
        </div>
      )}
      {icon && (
        <span className="app-empty-glyph" aria-hidden="true">
          {icon}
        </span>
      )}
      <p className="app-empty-title">{title}</p>
      {body && <p className="app-empty-body">{body}</p>}
      {actions && <div className="app-empty-actions">{actions}</div>}
    </div>
  );
}
