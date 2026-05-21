/**
 * Live tail of the running service's systemd journal.
 *
 * Connects to `/api/logs/tail?lines=<N>` (SSE). The backend streams one
 * `event: log` per journal entry plus a single `event: ready` on connect, or
 * a single `event: error` when the host doesn't have journalctl.
 *
 * UI features:
 * - history depth selector (default 500, configurable per page-load)
 * - text filter (case-insensitive substring)
 * - level threshold (only entries at or above the chosen level are shown)
 * - pause / resume + clear
 * - auto-scroll to bottom unless the user has scrolled up
 */

import {
  Badge,
  Box,
  Button,
  Group,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { IconRefresh, IconSearch, IconTrash } from "./Icons";

type LogEntry = {
  id: number;
  ts_ms: number | null;
  priority: number;
  level: string;
  message: string;
  unit?: string | null;
  ident?: string | null;
  pid?: string | null;
};

const DEFAULT_LINES = 500;
const MIN_LINES = 1;
const MAX_LINES = 50_000;
// Cap how many entries we keep in memory regardless of the requested
// history. A wide-open follow on a chatty backend can otherwise grow
// unbounded.
const MEMORY_CAP = 5_000;

// Journal priorities: 0 emerg .. 7 debug. The threshold is "show this and
// everything more severe", so a smaller priority is more severe. UI labels
// match `_PRIORITY_NAMES` in backend/logs/router.py.
const LEVEL_OPTIONS = [
  { value: "7", label: "Debug + above (all)" },
  { value: "6", label: "Info + above" },
  { value: "5", label: "Notice + above" },
  { value: "4", label: "Warning + above" },
  { value: "3", label: "Error + above" },
];

const LEVEL_COLOR: Record<string, string> = {
  emerg: "red",
  alert: "red",
  crit: "red",
  error: "red",
  warning: "yellow",
  notice: "blue",
  info: "gray",
  debug: "gray",
};

function formatTs(ms: number | null): string {
  if (ms === null) return "";
  const d = new Date(ms);
  const pad = (n: number, w = 2) => n.toString().padStart(w, "0");
  return (
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `.${pad(d.getMilliseconds(), 3)}`
  );
}

export function LogsPanel() {
  const [linesDraft, setLinesDraft] = useState<number | string>(DEFAULT_LINES);
  const [lines, setLines] = useState<number>(DEFAULT_LINES);
  const [filter, setFilter] = useState("");
  const [levelThreshold, setLevelThreshold] = useState("7");
  const [paused, setPaused] = useState(false);
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<"connecting" | "live" | "error" | "closed">("connecting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const seqRef = useRef(0);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickRef = useRef(true);

  // Reconnect every time the requested history depth changes; the backend
  // doesn't expose a way to change `-n` mid-stream.
  useEffect(() => {
    setEntries([]);
    setStatus("connecting");
    setErrorMessage(null);
    const es = new EventSource(`/api/logs/tail?lines=${lines}`);

    const onReady = () => {
      setStatus("live");
    };
    const onLog = (e: MessageEvent) => {
      if (pausedRef.current) return;
      let payload: Omit<LogEntry, "id">;
      try {
        payload = JSON.parse(e.data);
      } catch {
        return;
      }
      seqRef.current += 1;
      const entry: LogEntry = { id: seqRef.current, ...payload };
      setEntries((prev) => {
        const next =
          prev.length >= MEMORY_CAP ? prev.slice(prev.length - MEMORY_CAP + 1) : prev.slice();
        next.push(entry);
        return next;
      });
    };
    const onErrorEvent = (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data) as { message?: string };
        setErrorMessage(payload.message ?? "unknown error");
      } catch {
        setErrorMessage("unknown error");
      }
      setStatus("error");
    };
    const onConnectionError = () => {
      // EventSource auto-reconnects; surface the state so the user knows.
      setStatus((s) => (s === "live" ? "connecting" : s));
    };

    es.addEventListener("ready", onReady);
    es.addEventListener("log", onLog);
    es.addEventListener("error", onErrorEvent);
    es.onerror = onConnectionError;

    return () => {
      es.removeEventListener("ready", onReady);
      es.removeEventListener("log", onLog);
      es.removeEventListener("error", onErrorEvent);
      es.close();
    };
  }, [lines]);

  const threshold = Number(levelThreshold);
  const filterLower = filter.trim().toLowerCase();
  const visible = useMemo(() => {
    return entries.filter((e) => {
      if (e.priority > threshold) return false;
      if (filterLower && !e.message.toLowerCase().includes(filterLower)) return false;
      return true;
    });
  }, [entries, threshold, filterLower]);

  // Auto-scroll: snap to bottom on new entries unless the user scrolled up.
  // The dep on `visible.length` is what schedules the effect; the body
  // doesn't reference it directly, so we tell biome that's intentional.
  // biome-ignore lint/correctness/useExhaustiveDependencies: visible.length is a re-render trigger
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stickRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [visible.length]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickRef.current = distanceFromBottom < 24;
  };

  const applyLines = () => {
    const v = typeof linesDraft === "number" ? linesDraft : Number.parseInt(linesDraft, 10);
    if (!Number.isFinite(v)) return;
    const clamped = Math.max(MIN_LINES, Math.min(MAX_LINES, Math.trunc(v)));
    setLinesDraft(clamped);
    if (clamped !== lines) setLines(clamped);
  };

  const statusBadge = (() => {
    if (status === "live")
      return (
        <Badge color="green" variant="light">
          live
        </Badge>
      );
    if (status === "connecting")
      return (
        <Badge color="gray" variant="light">
          connecting…
        </Badge>
      );
    if (status === "error")
      return (
        <Badge color="red" variant="light">
          error
        </Badge>
      );
    return (
      <Badge color="gray" variant="light">
        closed
      </Badge>
    );
  })();

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end" wrap="wrap" gap="md">
        <Group gap="xs" align="flex-end" wrap="wrap">
          <NumberInput
            label="Lines"
            value={linesDraft}
            onChange={(v) => setLinesDraft(v)}
            onBlur={applyLines}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                applyLines();
              }
            }}
            min={MIN_LINES}
            max={MAX_LINES}
            step={100}
            clampBehavior="strict"
            w={140}
            description="History on connect"
          />
          <Select
            label="Level"
            data={LEVEL_OPTIONS}
            value={levelThreshold}
            onChange={(v) => v && setLevelThreshold(v)}
            allowDeselect={false}
            w={200}
          />
          <TextInput
            label="Filter"
            value={filter}
            onChange={(e) => setFilter(e.currentTarget.value)}
            placeholder="substring match…"
            leftSection={<IconSearch size={14} />}
            w={260}
          />
        </Group>
        <Group gap="xs" align="center">
          {statusBadge}
          <Text size="sm" c="dimmed" ff="monospace">
            {visible.length} / {entries.length}
          </Text>
          <Button
            variant="default"
            size="xs"
            onClick={() => setPaused((p) => !p)}
            aria-pressed={paused}
          >
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button
            variant="default"
            size="xs"
            leftSection={<IconRefresh size={14} />}
            onClick={() => setLines((n) => n)}
            title="Reconnect"
          >
            Reconnect
          </Button>
          <Button
            variant="default"
            size="xs"
            leftSection={<IconTrash size={14} />}
            onClick={() => setEntries([])}
          >
            Clear
          </Button>
        </Group>
      </Group>

      {errorMessage ? (
        <Box
          p="sm"
          style={{
            border: "1px solid var(--mantine-color-red-5)",
            borderRadius: "var(--mantine-radius-md)",
            background: "var(--mantine-color-red-0)",
            color: "var(--mantine-color-red-9)",
          }}
        >
          <Text size="sm">{errorMessage}</Text>
        </Box>
      ) : null}

      <Box
        ref={scrollRef}
        onScroll={onScroll}
        style={{
          border: "1px solid var(--app-border-subtle)",
          borderRadius: "var(--mantine-radius-md)",
          background: "var(--app-surface-muted)",
          height: "70vh",
          minHeight: 320,
          overflowY: "auto",
          fontFamily: "var(--app-mono)",
          fontSize: "0.78rem",
          lineHeight: 1.5,
        }}
      >
        {visible.length === 0 ? (
          <Box p="md">
            <Text size="sm" c="dimmed">
              {entries.length === 0
                ? status === "error"
                  ? "(no entries — see error above)"
                  : "(waiting for log entries…)"
                : "(no entries match the current filters)"}
            </Text>
          </Box>
        ) : (
          <Box component="ul" m={0} p={0} style={{ listStyle: "none" }}>
            {visible.map((e) => (
              <Box
                component="li"
                key={e.id}
                px="sm"
                py={2}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto auto 1fr",
                  gap: 10,
                  alignItems: "baseline",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  borderBottom: "1px solid var(--app-border-subtle)",
                }}
              >
                <Text component="span" size="xs" c="dimmed" ff="monospace">
                  {formatTs(e.ts_ms)}
                </Text>
                <Badge
                  size="xs"
                  variant="light"
                  color={LEVEL_COLOR[e.level] ?? "gray"}
                  style={{ minWidth: 56, justifyContent: "center" }}
                >
                  {e.level}
                </Badge>
                <Text component="span" size="xs" ff="monospace">
                  {e.message}
                </Text>
              </Box>
            ))}
          </Box>
        )}
      </Box>
    </Stack>
  );
}
