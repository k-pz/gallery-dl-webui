import { Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { ICON_SIZE, IconUpload } from "./Icons";

/**
 * Komga sync jobs: push series status only, or sync the full series-level
 * metadata (status, summary, language, reading direction, tags) — each
 * pushed field is locked so Komga's scan-time importers can't overwrite it.
 *
 * Credentials live in app_config (Config tab → Komga sync). The buttons just
 * schedule the jobs; the backend reads `komga_base_url` + `komga_api_key`
 * when the worker claims the job. If those aren't set, the schedule request
 * 400s with a "configure Komga" message that bubbles up through the parent.
 */
export function KomgaSyncCard({
  schedulingStatus,
  onScheduleStatus,
  schedulingMetadata,
  onScheduleMetadata,
}: {
  schedulingStatus: boolean;
  onScheduleStatus: () => void;
  schedulingMetadata: boolean;
  onScheduleMetadata: () => void;
}) {
  return (
    <Card>
      <Stack gap="md">
        <Stack gap={4}>
          <span className="app-section-kicker">komga sync</span>
          <Title order={3}>Sync to Komga</Title>
          <Text size="sm" c="dimmed">
            Pushes local series metadata to the matching Komga series, found by exact name match.
            Status-only pushes just the publication status (Ongoing / Ended / Hiatus / Abandoned);
            the full sync also covers summary, language, reading direction, and tags. Uses the API
            key + base URL configured in the Config tab.
          </Text>
        </Stack>
        <Group wrap="wrap">
          <Button
            variant="light"
            leftSection={<IconUpload size={ICON_SIZE.sm} />}
            onClick={onScheduleMetadata}
            loading={schedulingMetadata}
          >
            Sync metadata to Komga
          </Button>
          <Button
            variant="light"
            leftSection={<IconUpload size={ICON_SIZE.sm} />}
            onClick={onScheduleStatus}
            loading={schedulingStatus}
          >
            Push status only
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
