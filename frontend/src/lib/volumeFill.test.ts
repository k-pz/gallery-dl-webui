import { describe, expect, it } from "vitest";
import type { EpubChapterOut, EpubVolumeFillResult } from "../api/types.gen";
import {
  countMissingVolumes,
  isMangadexTitleUrl,
  lacksVolume,
  volumeFillMessage,
  volumeSourceUrl,
} from "./volumeFill";

const MD = "https://mangadex.org/title/0aea9f43-d4a9-4bf7-bebc-550a512f9b95/name";

describe("volumeSourceUrl", () => {
  it("recognises MangaDex title pages only", () => {
    expect(isMangadexTitleUrl(MD)).toBe(true);
    expect(isMangadexTitleUrl("mangadex.org/manga/0AEA9F43-D4A9-4BF7-BEBC-550A512F9B95")).toBe(
      true,
    );
    expect(
      isMangadexTitleUrl("https://mangadex.org/chapter/0aea9f43-d4a9-4bf7-bebc-550a512f9b95"),
    ).toBe(false);
    expect(isMangadexTitleUrl("https://example.org/?u=mangadex.org/title/x")).toBe(false);
  });

  it("prefers the series URL, then the metadata source URL", () => {
    expect(volumeSourceUrl({ url: MD, metadata_source_url: null })).toBe(MD);
    expect(volumeSourceUrl({ url: "https://weebcentral.com/s/1", metadata_source_url: MD })).toBe(
      MD,
    );
    expect(volumeSourceUrl({ url: "https://weebcentral.com/s/1", metadata_source_url: null })).toBe(
      null,
    );
  });
});

describe("missing volumes", () => {
  const ch = (number: string, volume: string): EpubChapterOut => ({
    number,
    volume,
    title: "",
    pages: 1,
    file_name: `${number}.cbz`,
    book_position: null,
  });

  it("treats empty and zero volumes as missing, hand-set text as present", () => {
    expect(lacksVolume("")).toBe(true);
    expect(lacksVolume("0")).toBe(true);
    expect(lacksVolume("2")).toBe(false);
    expect(lacksVolume("TBD")).toBe(false);
  });

  it("counts numbered chapters only", () => {
    expect(countMissingVolumes([ch("1", "1"), ch("2", ""), ch("3", "0"), ch("Extra", "")])).toBe(2);
  });
});

describe("volumeFillMessage", () => {
  const result = (over: Partial<EpubVolumeFillResult>): EpubVolumeFillResult =>
    ({
      source_url: MD,
      chapters: 3,
      missing: 2,
      filled: 2,
      unassigned: 0,
      failed: 0,
      errors: [],
      ...over,
    }) as EpubVolumeFillResult;

  it("summarises the outcome", () => {
    expect(volumeFillMessage(result({ missing: 0, filled: 0 }))).toBe(
      "Every chapter already has a volume.",
    );
    expect(volumeFillMessage(result({}))).toBe("2 chapters filled");
    expect(volumeFillMessage(result({ filled: 1, failed: 1, errors: ["c2: bad zip"] }))).toBe(
      "1 chapter filled · 1 failed — c2: bad zip",
    );
  });
});
