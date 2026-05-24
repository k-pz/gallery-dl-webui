import {
  Button,
  Card,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useState } from "react";
import { IconUpload } from "./Icons";

/**
 * Push the local `series_status` of every target into the matching Komga series.
 *
 * Credentials are collected in a modal on every run and sent inline with the
 * schedule request — they're held in worker memory just long enough to run
 * the job and then dropped. Nothing is persisted server-side beyond the job
 * row itself (which never sees the credentials).
 */
export function PushKomgaStatusCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: (params: { base_url: string; username: string; password: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const reset = () => {
    setBaseUrl("");
    setUsername("");
    setPassword("");
  };

  const close = () => {
    setOpen(false);
    // Drop the password from React state the moment the modal closes so it
    // doesn't sit around in memory between runs.
    reset();
  };

  const trimmedUrl = baseUrl.trim();
  const urlValid = /^https?:\/\//i.test(trimmedUrl);
  const canSubmit = urlValid && username.trim().length > 0 && password.length > 0 && !scheduling;

  const submit = () => {
    if (!canSubmit) return;
    onSchedule({
      base_url: trimmedUrl.replace(/\/+$/, ""),
      username: username.trim(),
      password,
    });
    close();
  };

  return (
    <Card>
      <Stack gap="md">
        <Stack gap={4}>
          <span className="app-section-kicker">komga sync</span>
          <Title order={3}>Push series status to Komga</Title>
          <Text size="sm" c="dimmed">
            Pushes every watched series' local status (Ongoing / Ended / Hiatus / Abandoned) to a
            matching Komga series, found by exact name match. Credentials are required on every run
            and are never stored on disk.
          </Text>
        </Stack>
        <Group>
          <Button
            variant="light"
            leftSection={<IconUpload size={14} />}
            onClick={() => setOpen(true)}
            loading={scheduling}
          >
            Push status to Komga…
          </Button>
        </Group>
      </Stack>

      <Modal opened={open} onClose={close} title="Push series status to Komga" centered size="md">
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Credentials are used once for this job and never written to the database. Re-enter them
            for each push.
          </Text>
          <TextInput
            label="Komga base URL"
            placeholder="https://komga.example.com"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.currentTarget.value)}
            error={baseUrl.length > 0 && !urlValid ? "Must start with http:// or https://" : null}
            autoFocus
            required
          />
          <TextInput
            label="Username (or email)"
            value={username}
            onChange={(e) => setUsername(e.currentTarget.value)}
            autoComplete="off"
            required
          />
          <PasswordInput
            label="Password"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            autoComplete="off"
            required
            onKeyDown={(e) => {
              if (e.key === "Enter" && canSubmit) submit();
            }}
          />
          <Group justify="flex-end" gap="sm">
            <Button variant="subtle" color="gray" onClick={close} disabled={scheduling}>
              Cancel
            </Button>
            <Button
              leftSection={<IconUpload size={14} />}
              onClick={submit}
              disabled={!canSubmit}
              loading={scheduling}
            >
              Push status
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}
