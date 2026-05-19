import { Group, Loader, Text, Title } from "@mantine/core";

/**
 * Title + count + spinner row shared by Library and Recent.
 *
 * The dimmed count reads "<visible> of <total>" when filters are active and
 * `formatTotal(total)` otherwise (defaulting to the bare number).
 */
export function ListHeader({
  title,
  titleOrder = 3,
  totalCount,
  visibleCount,
  filtersActive,
  isLoading,
  formatTotal,
}: {
  title: string;
  titleOrder?: 3 | 4;
  totalCount: number;
  visibleCount: number;
  filtersActive: boolean;
  isLoading?: boolean;
  formatTotal?: (n: number) => string;
}) {
  return (
    <Group justify="space-between" align="center" wrap="wrap">
      <Group gap="xs" align="center">
        <Title order={titleOrder}>{title}</Title>
        {totalCount > 0 && (
          <Text size="sm" c="dimmed">
            {filtersActive
              ? `${visibleCount} of ${totalCount}`
              : (formatTotal?.(totalCount) ?? `${totalCount}`)}
          </Text>
        )}
      </Group>
      {isLoading && <Loader size="xs" />}
    </Group>
  );
}
