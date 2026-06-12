/** Format an ISO timestamp as a short absolute local time ("Jun 10, 14:33"),
 * including the year only once it differs from the current one. */
export function formatAbs(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t);
  return d.toLocaleString(undefined, {
    ...(d.getFullYear() !== new Date().getFullYear() ? { year: "numeric" as const } : {}),
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Format a date-only ISO string ("2019-05-01" → "May 1, 2019").
 * A bare year ("2019") passes through as-is — some sources only expose that
 * much. Date-only strings parse as UTC midnight, so format in UTC to keep
 * the calendar day from shifting in negative-offset timezones. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  if (/^\d{4}$/.test(iso)) return iso;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(iso.includes("T") ? {} : { timeZone: "UTC" }),
  });
}

/** Format an ISO timestamp as a short relative-time string ("3h ago"). */
export function formatRel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(t).toLocaleDateString();
}
