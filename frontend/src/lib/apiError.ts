export function extractErrorMessage(err: unknown): string {
  const detail = (err as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (err instanceof Error) return err.message;
  return "request failed";
}
