import type { CSSProperties } from "react";

/**
 * Numeric badge that sits beside a tab label. Replaces the ambiguous "1/0"
 * tuple — when there's running work it reads "2 running"; when there's only
 * a backlog it muted-tones to "3 queued".
 */
export function CountBadge({
  running,
  queued,
  style,
}: {
  running: number;
  queued: number;
  style?: CSSProperties;
}) {
  if (running + queued === 0) return null;
  const tone = running > 0 ? "active" : "muted";
  const label = running > 0 ? `${running} running` : `${queued} queued`;
  // The visible label ("2 running" / "3 queued") already reads correctly when
  // rendered inside the Jobs tab, so we don't need a separate aria-label here.
  return (
    <span className="count-badge" data-tone={tone} style={style}>
      <span className="count-badge-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
