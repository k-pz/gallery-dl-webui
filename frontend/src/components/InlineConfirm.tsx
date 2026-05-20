import { Button, Group } from "@mantine/core";
import type { ReactNode } from "react";
import { IconAlertTriangle } from "./Icons";

/**
 * Slack-style inline destructive confirm. The strip replaces (or sits next to)
 * the row's normal actions until the user picks Confirm or Cancel.
 *
 * `confirmLabel` is the verb on the danger button; the leading icon is the
 * triangle by default. Sized to fit inside a table row or a card section.
 */
export function InlineConfirm({
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  loading,
  disabled,
}: {
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className="confirm-strip" role="alertdialog" aria-live="polite">
      <IconAlertTriangle
        size={18}
        className="alert-icon"
        style={{ color: "var(--tone-error)", flexShrink: 0, marginTop: 2 }}
      />
      <div className="confirm-msg">{message}</div>
      <Group gap="xs" wrap="nowrap">
        <Button size="xs" variant="subtle" color="gray" onClick={onCancel} disabled={loading}>
          {cancelLabel}
        </Button>
        <Button
          size="xs"
          color="red"
          variant="filled"
          loading={loading}
          disabled={disabled}
          onClick={onConfirm}
        >
          {confirmLabel}
        </Button>
      </Group>
    </div>
  );
}
