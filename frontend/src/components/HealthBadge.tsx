import { useQuery } from "@tanstack/react-query";
import { getHealthOptions } from "../api/@tanstack/react-query.gen";

/**
 * Compact health indicator shown in the page header. Renders as the
 * <span class="app-health" data-state="…"> pill defined in global.css —
 * one dot + one short label, in the body monospace so it reads as
 * diagnostic rather than promotional.
 */
export function HealthBadge() {
  // Poll so the badge can flip back to "unreachable" after a first success —
  // TanStack keeps the last data on error, so error must take precedence.
  const { data, isError } = useQuery({
    ...getHealthOptions(),
    refetchInterval: 30_000,
    retry: 1,
  });

  let state: "loading" | "ok" | "down" = "loading";
  let label = "checking";
  if (isError) {
    state = "down";
    label = "unreachable";
  } else if (data) {
    state = "ok";
    label = data.status;
  }

  return (
    <span className="app-health" data-state={state} aria-live="polite">
      <span className="app-health-dot" aria-hidden="true" />
      <span>backend</span>
      {/* The e2e tests look for the literal "ok" badge text inside the
          element labelled "backend", so we keep the raw status string. */}
      <span>·</span>
      <span>{label}</span>
    </span>
  );
}
