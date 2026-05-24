/**
 * Shared dispatch logic for backend-emitted events.
 *
 * Two transports feed it:
 * 1. The websocket stream (`useEventStream`) — every connected client
 *    receives every event, so two tabs viewing the same data stay in sync.
 * 2. The `X-Events` response header (`installResponseEventInterceptor`) —
 *    the mutating client also gets the events on its own HTTP response, so
 *    its TanStack cache invalidates synchronously instead of waiting for
 *    the websocket roundtrip. The two paths overlap for the mutating
 *    client, which is fine because `invalidateQueries` is idempotent.
 */

import type { useQueryClient } from "@tanstack/react-query";
import {
  getConfigQueryKey,
  getDownloadProgressQueryKey,
  getDownloadQueryKey,
  getMaintenanceJobProgressQueryKey,
  listDownloadsQueryKey,
  listMaintenanceJobsQueryKey,
  listOutputDirsQueryKey,
  listTargetsQueryKey,
} from "../api/@tanstack/react-query.gen";

export type BackendEvent = {
  topic: string;
  type: string;
  data: Record<string, unknown>;
};

export function handleBackendEvent(
  qc: ReturnType<typeof useQueryClient>,
  event: BackendEvent,
): void {
  switch (event.topic) {
    case "downloads": {
      qc.invalidateQueries({ queryKey: listDownloadsQueryKey() });
      const id = numberOrNull(event.data.id);
      if (id !== null) {
        qc.invalidateQueries({ queryKey: getDownloadQueryKey({ path: { download_id: id } }) });
        qc.invalidateQueries({
          queryKey: getDownloadProgressQueryKey({ path: { download_id: id } }),
        });
      }
      // Status transitions often refresh the joined target row too.
      qc.invalidateQueries({ queryKey: listTargetsQueryKey() });
      break;
    }
    case "progress": {
      const id = numberOrNull(event.data.download_id);
      if (id !== null) {
        qc.invalidateQueries({
          queryKey: getDownloadProgressQueryKey({ path: { download_id: id } }),
        });
      }
      // Maintenance progress events carry job_id.
      const jobId = numberOrNull(event.data.job_id);
      if (jobId !== null) {
        qc.invalidateQueries({
          queryKey: getMaintenanceJobProgressQueryKey({ path: { job_id: jobId } }),
        });
      }
      break;
    }
    case "targets":
      qc.invalidateQueries({ queryKey: listTargetsQueryKey() });
      break;
    case "config":
      qc.invalidateQueries({ queryKey: getConfigQueryKey() });
      qc.invalidateQueries({ queryKey: listOutputDirsQueryKey() });
      break;
    case "maintenance":
      qc.invalidateQueries({ queryKey: listMaintenanceJobsQueryKey() });
      break;
    default:
      // Unknown topic — ignore. The handshake / keep-alive lands here too.
      break;
  }
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
