import { useQuery } from "@tanstack/react-query";
import { getHealthOptions } from "../api/@tanstack/react-query.gen";

/**
 * Renders the running backend's version (the single source of truth — the
 * /api/health endpoint reports backend.__version__, which commitizen keeps in
 * sync with frontend/package.json on each `cz bump`). Shares the cache key
 * with HealthBadge so no extra request is made.
 */
export function AppVersion() {
  const { data } = useQuery(getHealthOptions());
  if (!data?.version) {
    return null;
  }
  return <span className="app-version">v{data.version}</span>;
}
