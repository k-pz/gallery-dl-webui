import { useQuery } from "@tanstack/react-query";
import { getHealthOptions } from "../api/@tanstack/react-query.gen";

/**
 * Compact health indicator shown in the page header. Renders as the
 * <span class="app-health" data-state="…"> pill defined in global.css —
 * one dot + one short label, in the body monospace so it reads as
 * diagnostic rather than promotional.
 */
export function HealthBadge() {
  const { data, error } = useQuery(getHealthOptions());

  let state: "loading" | "ok" | "down" = "loading";
  let label = "checking";
  if (data) {
    state = "ok";
    label = data.status;
  } else if (error) {
    state = "down";
    label = "unreachable";
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
