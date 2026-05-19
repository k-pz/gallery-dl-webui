import { useQueryClient } from "@tanstack/react-query";
import {
  getConfigQueryKey,
  getDownloadQueryKey,
  listDownloadsQueryKey,
  listOutputDirsQueryKey,
  listTargetsQueryKey,
} from "../api/@tanstack/react-query.gen";

/**
 * Named invalidators for the cached queries components reach for after
 * mutations. Components reuse the same names so it's easy to see what a
 * mutation touches without chasing query-key constants.
 */
export function useDataInvalidators() {
  const qc = useQueryClient();
  return {
    downloads: () => qc.invalidateQueries({ queryKey: listDownloadsQueryKey() }),
    targets: () => qc.invalidateQueries({ queryKey: listTargetsQueryKey() }),
    config: () => qc.invalidateQueries({ queryKey: getConfigQueryKey() }),
    outputDirs: () => qc.invalidateQueries({ queryKey: listOutputDirsQueryKey() }),
    download: (id: number) =>
      qc.invalidateQueries({
        queryKey: getDownloadQueryKey({ path: { download_id: id } }),
      }),
  };
}
