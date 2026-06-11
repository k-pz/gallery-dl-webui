/**
 * Shared cancel/requeue mutations for download jobs.
 *
 * ActiveJobCard (single-job view) and RecentList (list view) need the same
 * wiring: flag the optimistic-cancel intent, invalidate the downloads list +
 * the affected job, and toast the outcome. The only thing that differs per
 * call site is how the cancel intent is tracked and what extra state to
 * update — both come in through the options.
 */

import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { cancelDownloadMutation, requeueDownloadMutation } from "../api/@tanstack/react-query.gen";
import { cancelDownload } from "../api/sdk.gen";
import { useDataInvalidators } from "./invalidate";
import { useNotifyingMutation } from "./useNotifyingMutation";

type DownloadActionOptions = {
  /** Called from onMutate (cancel) with the job id — flag the cancel intent. */
  markCancelling?: (id: number) => void;
  /** Called when a cancel fails or a requeue starts — clear the intent. */
  clearCancelling?: (id: number) => void;
  onSuccess?: (id: number) => void;
  onError?: (err: unknown, id: number) => void;
};

export function useCancelDownload(opts: DownloadActionOptions = {}) {
  const invalidate = useDataInvalidators();
  return useNotifyingMutation(
    {
      ...cancelDownloadMutation(),
      onMutate: (vars) => {
        opts.markCancelling?.(vars.path.download_id);
      },
      onSuccess: (d) => {
        invalidate.downloads();
        invalidate.download(d.id);
        opts.onSuccess?.(d.id);
      },
      onError: (err, vars) => {
        opts.clearCancelling?.(vars.path.download_id);
        opts.onError?.(err, vars.path.download_id);
      },
    },
    {
      success: {
        title: "Cancel requested",
        message: (d) => `Job #${d.id} is being cancelled.`,
        color: "orange",
      },
      error: { title: (_err, vars) => `Cancel failed (#${vars.path.download_id})` },
    },
  );
}

export function useRequeueDownload(opts: DownloadActionOptions = {}) {
  const invalidate = useDataInvalidators();
  return useNotifyingMutation(
    {
      ...requeueDownloadMutation(),
      onMutate: (vars) => {
        opts.clearCancelling?.(vars.path.download_id);
      },
      onSuccess: (d) => {
        invalidate.downloads();
        invalidate.download(d.id);
        opts.onSuccess?.(d.id);
      },
      onError: (err, vars) => {
        opts.onError?.(err, vars.path.download_id);
      },
    },
    {
      success: {
        title: "Requeued",
        message: (d) => `Job #${d.id} has been queued again.`,
        color: "blue",
      },
      error: { title: (_err, vars) => `Requeue failed (#${vars.path.download_id})` },
    },
  );
}

/**
 * Cancel every job in `ids` with one summary toast instead of one per job.
 * Failures don't abort the batch — each id gets its own request and the
 * toast reports how many went through.
 */
export function useCancelAllDownloads() {
  const invalidate = useDataInvalidators();
  return useMutation({
    mutationFn: async (ids: number[]) => {
      const results = await Promise.allSettled(
        ids.map((id) => cancelDownload({ path: { download_id: id }, throwOnError: true })),
      );
      const failed = results.filter((r) => r.status === "rejected").length;
      return { requested: ids.length, failed };
    },
    onSettled: () => invalidate.downloads(),
    onSuccess: ({ requested, failed }) => {
      if (failed > 0) {
        notifications.show({
          title: "Cancel all",
          message: `${requested - failed} of ${requested} cancel requests sent — ${failed} failed.`,
          color: "red",
        });
      } else {
        notifications.show({
          title: "Cancel all",
          message: `Cancel requested for ${requested} job${requested === 1 ? "" : "s"}.`,
          color: "orange",
        });
      }
    },
  });
}
