/**
 * Realtime event-stream hook.
 *
 * Connects to the backend's `/api/ws` websocket and pushes each event into the
 * TanStack Query cache via targeted invalidations. The component-side
 * `refetchInterval` polling is left in place as a generous fallback for when
 * the socket is dropped (proxy timeouts, suspended laptops, etc.) — but in
 * normal operation the cache is kept fresh by the websocket, so the UI
 * "feels" event-driven rather than polled.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import {
  getConfigQueryKey,
  listDownloadsQueryKey,
  listMaintenanceJobsQueryKey,
  listTargetsQueryKey,
} from "../api/@tanstack/react-query.gen";
import { type BackendEvent, handleBackendEvent } from "./backendEvents";

function buildWsUrl(): string {
  if (typeof window === "undefined") {
    return "";
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/ws`;
}

/**
 * Open one WS connection for the lifetime of the app. Reconnect with
 * exponential backoff so a transient network blip doesn't drop us into
 * polling-only mode.
 */
export function useEventStream(): void {
  const qc = useQueryClient();

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let retryDelay = 1000;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (stopped) return;
      try {
        ws = new WebSocket(buildWsUrl());
      } catch {
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        retryDelay = 1000;
        // On (re)connect, force a refresh of every cached list — anything that
        // changed while we were disconnected was missed by the event stream.
        qc.invalidateQueries({ queryKey: listDownloadsQueryKey() });
        qc.invalidateQueries({ queryKey: listTargetsQueryKey() });
        qc.invalidateQueries({ queryKey: getConfigQueryKey() });
        qc.invalidateQueries({ queryKey: listMaintenanceJobsQueryKey() });
      };

      ws.onmessage = (msg) => {
        let event: BackendEvent | null = null;
        try {
          event = JSON.parse(msg.data) as BackendEvent;
        } catch {
          return;
        }
        handleBackendEvent(qc, event);
      };

      ws.onclose = () => {
        ws = null;
        scheduleReconnect();
      };

      ws.onerror = () => {
        // Close handler will run too; let it schedule the reconnect.
        try {
          ws?.close();
        } catch {
          // ignore
        }
      };
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      if (reconnectTimer !== null) return;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        retryDelay = Math.min(retryDelay * 2, 15000);
        connect();
      }, retryDelay);
    };

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      ws?.close();
      ws = null;
    };
  }, [qc]);
}
