import type { ReactNode } from "react";
import { ICON_SIZE, IconArrowUp } from "./Icons";

/**
 * Glyph + title + body + secondary action. `arrow` adds a directional cue
 * pointing at the form above the empty state — used on the library tab to
 * say "type a URL up there".
 */
export function EmptyState({
  icon,
  title,
  body,
  actions,
  arrow,
}: {
  icon: ReactNode;
  title: string;
  body?: ReactNode;
  actions?: ReactNode;
  arrow?: boolean;
}) {
  return (
    <div className="app-empty">
      {arrow && (
        <div className="app-empty-arrow" aria-hidden="true">
          <IconArrowUp size={ICON_SIZE.lg} />
        </div>
      )}
      <span className="app-empty-glyph" aria-hidden="true">
        {icon}
      </span>
      <p className="app-empty-title">{title}</p>
      {body && <p className="app-empty-body">{body}</p>}
      {actions && <div className="app-empty-actions">{actions}</div>}
    </div>
  );
}
