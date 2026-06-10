/**
 * SSE transport for the live journal tail (`/api/logs/tail`).
 *
 * Owns the EventSource lifecycle so the LogsPanel can stay presentational:
 * - reconnects when the requested history depth changes or `reconnect()` is
 *   called (the backend can't change `-n` mid-stream);
 * - distinguishes the backend's custom `event: error` payloads from the
 *   *native* EventSource connection-error events (both arrive on the same
 *   "error" listener — a native drop must show "connecting…", not a fatal
 *   error);
 * - buffers entries received while paused and flushes them on resume, so
 *   Pause never loses log lines.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type LogEntry = {
  id: number;
  ts_ms: number | null;
  priority: number;
  level: string;
  message: string;
  unit?: string | null;
  ident?: string | null;
  pid?: string | null;
};

export type LogTailStatus = "connecting" | "live" | "error" | "closed";

// Cap how many entries we keep in memory regardless of the requested
// history. A wide-open follow on a chatty backend can otherwise grow
// unbounded.
export const MEMORY_CAP = 5_000;

function capped(prev: LogEntry[], batch: LogEntry[]): LogEntry[] {
  const next = prev.concat(batch);
  return next.length > MEMORY_CAP ? next.slice(next.length - MEMORY_CAP) : next;
}

export function useLogTail(lines: number, { paused }: { paused: boolean }) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<LogTailStatus>("connecting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Bumping the nonce re-runs the connection effect with the same `lines` —
  // the Reconnect button. (Setting state to an identical value would bail
  // out of the re-render entirely.)
  const [reconnectNonce, setReconnectNonce] = useState(0);

  const seqRef = useRef(0);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  // Entries received while paused; flushed on resume.
  const pendingRef = useRef<LogEntry[]>([]);

  useEffect(() => {
    if (!paused && pendingRef.current.length > 0) {
      const batch = pendingRef.current;
      pendingRef.current = [];
      setEntries((prev) => capped(prev, batch));
    }
  }, [paused]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reconnectNonce is an intentional re-run trigger
  useEffect(() => {
    setEntries([]);
    pendingRef.current = [];
    setStatus("connecting");
    setErrorMessage(null);
    const es = new EventSource(`/api/logs/tail?lines=${lines}`);

    const onReady = () => {
      setStatus("live");
    };
    const onLog = (e: MessageEvent) => {
      let payload: Omit<LogEntry, "id">;
      try {
        payload = JSON.parse(e.data);
      } catch {
        return;
      }
      seqRef.current += 1;
      const entry: LogEntry = { id: seqRef.current, ...payload };
      if (pausedRef.current) {
        // Keep the paused backlog bounded the same way as the live list.
        pendingRef.current = capped(pendingRef.current, [entry]);
        return;
      }
      setEntries((prev) => capped(prev, [entry]));
    };
    const onErrorEvent = (e: Event) => {
      // Native connection errors are plain Events on the same "error" type
      // as the backend's custom payloads; they're handled by onerror below.
      if (!(e instanceof MessageEvent) || typeof e.data !== "string") return;
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
  }, [lines, reconnectNonce]);

  const clear = useCallback(() => {
    pendingRef.current = [];
    setEntries([]);
  }, []);

  const reconnect = useCallback(() => {
    setReconnectNonce((n) => n + 1);
  }, []);

  return { entries, status, errorMessage, clear, reconnect };
}
