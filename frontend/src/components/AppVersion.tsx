import { useQuery } from "@tanstack/react-query";
import { getHealthOptions, getUpdatePreviewRefOptions } from "../api/@tanstack/react-query.gen";

/**
 * Renders the running backend's version (the single source of truth — the
 * /api/health endpoint reports backend.__version__, which commitizen keeps in
 * sync with frontend/package.json on each `cz bump`). Shares the cache key
 * with HealthBadge so no extra request is made.
 *
 * When the maintenance card has a non-default preview ref configured, the
 * tracked ref takes over as the primary label and the installed version
 * trails in parentheses — the footer should reflect what the user has
 * pointed the LXC at, not just the build that's actually running.
 */
export function AppVersion() {
  const { data } = useQuery(getHealthOptions());
  // react-query dedupes with the maintenance card's identical subscription,
  // so this is a free read once that panel has been opened — and a single
  // cheap request otherwise.
  const previewRef = useQuery(getUpdatePreviewRefOptions());
  if (!data?.version) {
    return null;
  }
  const ref = previewRef.data?.ref ?? null;
  const installed = `v${data.version}`;
  if (ref) {
    return (
      <span className="app-version">
        {ref} <span className="app-version-installed">({installed})</span>
      </span>
    );
  }
  return <span className="app-version">{installed}</span>;
}
