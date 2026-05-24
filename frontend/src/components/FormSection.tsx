import { Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";

export function FormSection({
  kicker,
  title,
  description,
  children,
}: {
  kicker: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Stack gap="md">
      <Stack gap={4}>
        <span className="app-section-kicker">{kicker}</span>
        <Title order={4}>{title}</Title>
        {description && (
          <Text size="sm" c="dimmed">
            {description}
          </Text>
        )}
      </Stack>
      {children}
    </Stack>
  );
}
