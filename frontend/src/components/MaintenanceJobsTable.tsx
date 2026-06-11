import { Box, Loader, Stack, Table, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { useState } from "react";
import type { MaintenanceJob } from "../api/types.gen";
import { KIND_LABEL, maintStatusLabel, TERMINAL_STATUSES } from "../lib/maintenance";
import { statusTone } from "../lib/status";
import { ICON_SIZE, IconChevronDown, IconX } from "./Icons";
import { Pill } from "./Pill";

/** The maintenance job history table: one selectable row per job, with an
 * expandable result payload and a cancel affordance for non-terminal jobs. */
export function MaintenanceJobsTable({
  jobs,
  selectedJobId,
  onSelect,
  cancellingJobId,
  onCancel,
}: {
  jobs: readonly MaintenanceJob[];
  selectedJobId: number | null;
  onSelect: (id: number) => void;
  /** Job id with a cancel in flight (guards double-clicks), or null. */
  cancellingJobId: number | null;
  onCancel: (id: number) => void;
}) {
  return (
    <Box
      style={{
        border: "1px solid var(--app-border-subtle)",
        borderRadius: "var(--mantine-radius-md)",
        overflow: "hidden",
      }}
    >
      <Table verticalSpacing="sm" highlightOnHover stickyHeader className="maint-jobs-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th style={{ width: 64 }}>ID</Table.Th>
            <Table.Th>Job</Table.Th>
            <Table.Th style={{ width: 140 }}>Status</Table.Th>
            <Table.Th>Result</Table.Th>
            <Table.Th style={{ width: 56 }} aria-label="Actions" />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {jobs.map((job) => {
            const cancellable = !TERMINAL_STATUSES.has(job.status);
            const isSelected = selectedJobId === job.id;
            const isCancelling = cancellingJobId === job.id;
            return (
              <Table.Tr
                key={job.id}
                onClick={() => onSelect(job.id)}
                style={{
                  cursor: "pointer",
                  backgroundColor: isSelected ? "var(--app-surface-muted)" : undefined,
                }}
                aria-label={`Select maintenance job ${job.id}`}
              >
                <Table.Td>
                  <Text size="sm" ff="monospace" c="dimmed">
                    {job.id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Stack gap={2}>
                    <Text size="sm" fw={500}>
                      {KIND_LABEL[job.kind] ?? job.kind}
                    </Text>
                    <Text size="xs" c="dimmed" ff="monospace">
                      {job.kind}
                    </Text>
                  </Stack>
                </Table.Td>
                <Table.Td>
                  <Pill tone={statusTone(job.status)}>{maintStatusLabel(job.status)}</Pill>
                </Table.Td>
                <Table.Td>
                  <Stack gap={4}>
                    {job.kind === "push_komga_series_status" && (
                      <KomgaMatchWarnings result={job.result} />
                    )}
                    <MaintResultCell
                      text={job.result ? JSON.stringify(job.result) : (job.error ?? "—")}
                      empty={!job.result && !job.error}
                      jobId={job.id}
                    />
                  </Stack>
                </Table.Td>
                <Table.Td>
                  {cancellable && (
                    <Tooltip label="Cancel job" withArrow>
                      <button
                        type="button"
                        className="icon-btn"
                        data-tone="danger"
                        aria-label={`Cancel maintenance job ${job.id}`}
                        // aria-disabled (not native `disabled`) keeps the
                        // button hoverable so the Tooltip still fires while
                        // the cancel is in flight; the click is guarded below.
                        aria-disabled={isCancelling ? "true" : undefined}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (isCancelling) return;
                          onCancel(job.id);
                        }}
                      >
                        {isCancelling ? (
                          <Loader size={16} color="red" />
                        ) : (
                          <IconX size={ICON_SIZE.md} />
                        )}
                      </button>
                    </Tooltip>
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Box>
  );
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

/** Names the series a Komga push couldn't sync, so the user knows what to fix.
 *
 * The push job's result carries `unmatched` (no Komga series with that name)
 * and `ambiguous` (several exact matches) alongside the counters; rendering
 * them here saves digging through the raw JSON or the job log.
 */
function KomgaMatchWarnings({ result }: { result: { [key: string]: unknown } | null }) {
  const unmatched = stringList(result?.unmatched);
  const ambiguous = stringList(result?.ambiguous);
  if (unmatched.length === 0 && ambiguous.length === 0) return null;
  return (
    <Stack gap={2}>
      {unmatched.length > 0 && (
        <Text size="xs" c="orange">
          No Komga match ({unmatched.length}): {unmatched.join(", ")}
        </Text>
      )}
      {ambiguous.length > 0 && (
        <Text size="xs" c="orange">
          Ambiguous Komga match ({ambiguous.length}): {ambiguous.join(", ")}
        </Text>
      )}
    </Stack>
  );
}

function MaintResultCell({ text, empty, jobId }: { text: string; empty: boolean; jobId: number }) {
  const [expanded, setExpanded] = useState(false);

  // No payload and no error: nothing to expand, just the placeholder.
  if (empty) {
    return (
      <Text size="xs" ff="monospace" c="dimmed">
        {text}
      </Text>
    );
  }

  return (
    <Stack gap={4} className="maint-result-wrap">
      {expanded ? (
        <Text
          size="xs"
          ff="monospace"
          c="dimmed"
          className="maint-result maint-result-full"
          data-testid={`maint-result-full-${jobId}`}
        >
          {text}
        </Text>
      ) : (
        <Text size="xs" ff="monospace" c="dimmed" className="maint-result">
          {text}
        </Text>
      )}
      <UnstyledButton
        className="maint-result-toggle"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
        aria-expanded={expanded}
        aria-label={
          expanded
            ? `Collapse result for maintenance job ${jobId}`
            : `Expand result for maintenance job ${jobId}`
        }
        data-expanded={expanded ? "true" : undefined}
      >
        {/* Color comes from .maint-result-toggle (accent) — no c prop. */}
        <Text size="xs" ff="monospace">
          {expanded ? "collapse" : "expand"}
        </Text>
        <IconChevronDown size={ICON_SIZE.sm} className="maint-result-toggle-chev" />
      </UnstyledButton>
    </Stack>
  );
}
