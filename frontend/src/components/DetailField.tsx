import { Stack, Text } from "@mantine/core";

export function DetailField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" style={{ letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {label}
      </Text>
      <Text size="sm" ff={mono ? "monospace" : undefined}>
        {value}
      </Text>
    </Stack>
  );
}
