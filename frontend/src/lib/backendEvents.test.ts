/**
 * The topic → query-key dispatch is the mechanism that keeps every panel
 * fresh; a regression here silently degrades the app into stale polling.
 * Tested against a real QueryClient by spying on invalidateQueries.
 */

import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
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
import { handleBackendEvent } from "./backendEvents";

function setup() {
  const qc = new QueryClient();
  const invalidated: unknown[] = [];
  vi.spyOn(qc, "invalidateQueries").mockImplementation(((filters: { queryKey?: unknown }) => {
    invalidated.push(filters?.queryKey);
    return Promise.resolve();
  }) as typeof qc.invalidateQueries);
  return { qc, invalidated };
}

describe("handleBackendEvent", () => {
  it("downloads events invalidate the list, the job, its progress, and targets", () => {
    const { qc, invalidated } = setup();
    handleBackendEvent(qc, { topic: "downloads", type: "updated", data: { id: 7 } });
    expect(invalidated).toEqual([
      listDownloadsQueryKey(),
      getDownloadQueryKey({ path: { download_id: 7 } }),
      getDownloadProgressQueryKey({ path: { download_id: 7 } }),
      listTargetsQueryKey(),
    ]);
  });

  it("downloads events without an id still refresh the lists", () => {
    const { qc, invalidated } = setup();
    handleBackendEvent(qc, { topic: "downloads", type: "updated", data: {} });
    expect(invalidated).toEqual([listDownloadsQueryKey(), listTargetsQueryKey()]);
  });

  it("progress events target the download or maintenance progress query", () => {
    const { qc, invalidated } = setup();
    handleBackendEvent(qc, { topic: "progress", type: "file", data: { download_id: 3 } });
    handleBackendEvent(qc, { topic: "progress", type: "step", data: { job_id: 9 } });
    expect(invalidated).toEqual([
      getDownloadProgressQueryKey({ path: { download_id: 3 } }),
      getMaintenanceJobProgressQueryKey({ path: { job_id: 9 } }),
    ]);
  });

  it("targets, config and maintenance topics hit their lists", () => {
    const { qc, invalidated } = setup();
    handleBackendEvent(qc, { topic: "targets", type: "updated", data: {} });
    handleBackendEvent(qc, { topic: "config", type: "updated", data: {} });
    handleBackendEvent(qc, { topic: "maintenance", type: "updated", data: {} });
    expect(invalidated).toEqual([
      listTargetsQueryKey(),
      getConfigQueryKey(),
      listOutputDirsQueryKey(),
      listMaintenanceJobsQueryKey(),
    ]);
  });

  it("ignores unknown topics and non-numeric ids", () => {
    const { qc, invalidated } = setup();
    handleBackendEvent(qc, { topic: "keepalive", type: "ping", data: {} });
    handleBackendEvent(qc, { topic: "progress", type: "file", data: { download_id: "3" } });
    expect(invalidated).toEqual([]);
  });
});
