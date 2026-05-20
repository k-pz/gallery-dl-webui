import { ActionIcon, Tooltip } from "@mantine/core";

export type SortDir = "asc" | "desc";

/**
 * Direction-flip control rendered next to a "Sort by" Select. Labels adapt to
 * the sort key so the tooltip reads as "Newest first" rather than just "desc".
 */
export function SortDirToggle({
  dir,
  sortKey,
  onToggle,
}: {
  dir: SortDir;
  sortKey: string;
  onToggle: (next: SortDir) => void;
}) {
  const next: SortDir = dir === "desc" ? "asc" : "desc";
  const current = describe(sortKey, dir);
  const after = describe(sortKey, next);
  return (
    <Tooltip label={`${current} — click for ${after.toLowerCase()}`} withArrow>
      <ActionIcon
        variant="default"
        size="lg"
        onClick={() => onToggle(next)}
        aria-label={`Sort direction: ${current}. Click to switch to ${after.toLowerCase()}.`}
      >
        {dir === "desc" ? "↓" : "↑"}
      </ActionIcon>
    </Tooltip>
  );
}

function describe(sortKey: string, dir: SortDir): string {
  if (sortKey === "name") return dir === "asc" ? "A → Z" : "Z → A";
  if (sortKey === "status") return dir === "asc" ? "Earliest stage first" : "Latest stage first";
  return dir === "asc" ? "Oldest first" : "Newest first";
}
