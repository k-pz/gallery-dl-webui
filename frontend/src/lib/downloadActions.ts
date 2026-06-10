/**
 * Shared cancel/requeue mutations for download jobs.
 *
 * ActiveJobCard (single-job view) and RecentList (list view) need the same
 * wiring: flag the optimistic-cancel intent, invalidate the downloads list +
 * the affected job, and toast the outcome. The only thing that differs per
 * call site is how the cancel intent is tracked and what extra state to
 * update — both come in through the options.
 */

import { cancelDownloadMutation, requeueDownloadMutation } from "../api/@tanstack/react-query.gen";
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
