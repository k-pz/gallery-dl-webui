import { Group, Pagination, Text } from "@mantine/core";

/**
 * Footer row with "showing X–Y of Z" plus Mantine Pagination. Renders nothing
 * when there's only a single page so short lists don't get a useless control.
 */
export function ListPagination({
  page,
  setPage,
  totalPages,
  start,
  end,
  total,
  ariaLabel,
}: {
  page: number;
  setPage: (n: number) => void;
  totalPages: number;
  start: number;
  end: number;
  total: number;
  ariaLabel?: string;
}) {
  if (totalPages <= 1) return null;
  return (
    <Group justify="space-between" align="center" wrap="wrap">
      <Text size="xs" c="dimmed">
        {start + 1}–{end} of {total}
      </Text>
      <Pagination
        value={page}
        onChange={setPage}
        total={totalPages}
        size="sm"
        siblings={1}
        boundaries={1}
        aria-label={ariaLabel}
      />
    </Group>
  );
}
