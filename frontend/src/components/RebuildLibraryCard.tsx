import { Button, Card, Group, Stack, Text, TextInput, Title } from "@mantine/core";
import { useMemo, useState } from "react";
import { ICON_SIZE, IconAlertTriangle } from "./Icons";

// The literal the user must type to arm the rebuild. Kept short, lowercase
// only — anything longer becomes annoying to type for a deliberately
// frequent-enough op.
const REBUILD_CONFIRM_WORD = "rebuild";

/**
 * Destructive op lives on its own card with a red border and a type-to-confirm
 * field. The button doesn't accept the click until the user has typed exactly
 * `rebuild`, so a stray cursor never wipes anyone's library.
 */
export function RebuildLibraryCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const [typed, setTyped] = useState("");
  const matches = useMemo(() => typed.trim().toLowerCase() === REBUILD_CONFIRM_WORD, [typed]);

  const reset = () => {
    setArmed(false);
    setTyped("");
  };

  return (
    <Card className="maintenance-destructive">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
            <span className="app-section-kicker">destructive</span>
            <Title order={3} style={{ color: "var(--tone-error)" }}>
              Rebuild library
            </Title>
            <Text size="sm" c="dimmed">
              Wipes every downloaded chapter, the gallery-dl archive, the raw downloads dir, and
              everything under the postprocess root (excluded directory names are spared). Every
              watched series is re-queued from scratch. There's no undo. Expect the library to be
              rebuilding — and downloads to stay incomplete — for several hours.
            </Text>
          </Stack>
          <IconAlertTriangle
            size={ICON_SIZE.xl}
            style={{ color: "var(--tone-error)", flexShrink: 0 }}
          />
        </Group>
        {!armed ? (
          <Group>
            <Button
              variant="outline"
              color="red"
              leftSection={<IconAlertTriangle size={ICON_SIZE.sm} />}
              onClick={() => setArmed(true)}
              loading={scheduling}
            >
              Rebuild library…
            </Button>
          </Group>
        ) : (
          <Stack gap="sm">
            <Text size="sm">
              To confirm, type <span className="code-chip">{REBUILD_CONFIRM_WORD}</span> below. The
              next run is scheduled immediately and cannot be reverted.
            </Text>
            <Group gap="sm" wrap="wrap" align="flex-end">
              <TextInput
                aria-label="Type rebuild to confirm"
                placeholder={REBUILD_CONFIRM_WORD}
                value={typed}
                onChange={(e) => setTyped(e.currentTarget.value)}
                style={{ flex: 1, minWidth: 200, maxWidth: 240 }}
                styles={{ input: { fontFamily: "var(--app-mono)" } }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && matches) {
                    onSchedule();
                    reset();
                  }
                }}
                autoFocus
              />
              <Button
                color="red"
                leftSection={<IconAlertTriangle size={ICON_SIZE.sm} />}
                disabled={!matches}
                loading={scheduling}
                onClick={() => {
                  onSchedule();
                  reset();
                }}
              >
                Rebuild library
              </Button>
              <Button variant="subtle" color="gray" onClick={reset} disabled={scheduling}>
                Cancel
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
