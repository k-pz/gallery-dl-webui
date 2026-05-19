import { Group, Stack, TextInput } from "@mantine/core";
import type { ReactNode } from "react";

/**
 * Filter row with a search TextInput plus a slot for domain-specific Selects.
 *
 * `belowChildren` renders an extra row below the toolbar (e.g. SegmentedControl
 * for watched/unwatched in Library); when present, the whole thing wraps in a
 * Stack so both rows share consistent vertical spacing.
 */
export function ListToolbar({
  search,
  setSearch,
  searchPlaceholder = "Search",
  searchAriaLabel,
  searchMinWidth = 180,
  children,
  belowChildren,
}: {
  search: string;
  setSearch: (s: string) => void;
  searchPlaceholder?: string;
  searchAriaLabel?: string;
  searchMinWidth?: number;
  children?: ReactNode;
  belowChildren?: ReactNode;
}) {
  const row = (
    <Group gap="xs" align="flex-end" wrap="wrap">
      <TextInput
        placeholder={searchPlaceholder}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        style={{ flex: 1, minWidth: searchMinWidth }}
        aria-label={searchAriaLabel ?? searchPlaceholder}
      />
      {children}
    </Group>
  );
  if (!belowChildren) return row;
  return (
    <Stack gap="xs">
      {row}
      {belowChildren}
    </Stack>
  );
}
