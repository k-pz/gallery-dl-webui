/**
 * Reads the backend's `X-Events` response header and feeds the events
 * through `handleBackendEvent`. Wired into the generated API client's
 * response interceptor chain at app boot so every mutation's response
 * synchronously invalidates the right TanStack caches — no waiting for
 * the websocket to deliver the same events.
 */

import type { QueryClient } from "@tanstack/react-query";

import { client } from "../api/client.gen";
import { type BackendEvent, handleBackendEvent } from "./backendEvents";

const HEADER_NAME = "X-Events";

export function installResponseEventInterceptor(qc: QueryClient): () => void {
  const handler = (response: Response): Response => {
    const raw = response.headers.get(HEADER_NAME);
    if (!raw) return response;
    let events: BackendEvent[] = [];
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        events = parsed as BackendEvent[];
      }
    } catch {
      // Malformed header — fall back to the websocket. Don't spam the
      // console; this is benign.
      return response;
    }
    for (const event of events) {
      if (event && typeof event === "object" && typeof event.topic === "string") {
        handleBackendEvent(qc, event);
      }
    }
    return response;
  };

  client.interceptors.response.use(handler);
  return () => {
    client.interceptors.response.eject(handler);
  };
}
