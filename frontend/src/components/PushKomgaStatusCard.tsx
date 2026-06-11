import { Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { ICON_SIZE, IconUpload } from "./Icons";

/**
 * Push the local `series_status` of every target into the matching Komga series.
 *
 * Credentials live in app_config (Config tab → Komga sync). The button just
 * schedules the job; the backend reads `komga_base_url` + `komga_api_key`
 * when the worker claims the job. If those aren't set, the schedule request
 * 400s with a "configure Komga" message that bubbles up through the parent.
 */
export function PushKomgaStatusCard({
  scheduling,
  onSchedule,
}: {
  scheduling: boolean;
  onSchedule: () => void;
}) {
  return (
    <Card>
      <Stack gap="md">
        <Stack gap={4}>
          <span className="app-section-kicker">komga sync</span>
          <Title order={3}>Push series status to Komga</Title>
          <Text size="sm" c="dimmed">
            Pushes every watched series' local status (Ongoing / Ended / Hiatus / Abandoned) to a
            matching Komga series, found by exact name match. Uses the API key + base URL configured
            in the Config tab.
          </Text>
        </Stack>
        <Group>
          <Button
            variant="light"
            leftSection={<IconUpload size={ICON_SIZE.sm} />}
            onClick={onSchedule}
            loading={scheduling}
          >
            Push status to Komga
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
