import type { EpubChapterOut, EpubVolumeFillResult, Target } from "../api/types.gen";

// Mirrors backend/volume_fill/library.py MANGADEX_TITLE_URL.
const MANGADEX_TITLE_URL =
  /^(?:https?:\/\/)?(?:www\.)?mangadex\.(?:org|cc)\/(?:title|manga)\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:[/?#]|$)/i;

export function isMangadexTitleUrl(url: string | null | undefined): boolean {
  return !!url && MANGADEX_TITLE_URL.test(url.trim());
}

/**
 * The MangaDex page volumes are read from: the series URL when it is a
 * MangaDex title, otherwise its metadata source URL when that is one.
 */
export function volumeSourceUrl(
  target: Pick<Target, "url" | "metadata_source_url">,
): string | null {
  for (const url of [target.url, target.metadata_source_url]) {
    if (url && isMangadexTitleUrl(url)) return url.trim();
  }
  return null;
}

/** Same rule as the backend: empty, or a number <= 0, means "no volume". */
export function lacksVolume(volume: string): boolean {
  const text = volume.trim();
  if (!text) return true;
  const n = Number(text);
  return Number.isFinite(n) && n <= 0;
}

/** Numbered chapters on disk whose ComicInfo has no volume. */
export function countMissingVolumes(chapters: ReadonlyArray<EpubChapterOut>): number {
  return chapters.filter((c) => Number.isFinite(Number(c.number)) && lacksVolume(c.volume)).length;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** One-line outcome for the notification after a fill. */
export function volumeFillMessage(result: EpubVolumeFillResult): string {
  if (result.missing === 0) return "Every chapter already has a volume.";
  const parts = [`${plural(result.filled, "chapter")} filled`];
  if (result.unassigned > 0) parts.push(`${result.unassigned} not in a volume on MangaDex yet`);
  if (result.failed > 0) parts.push(`${result.failed} failed — ${result.errors[0] ?? ""}`.trim());
  return parts.join(" · ");
}
