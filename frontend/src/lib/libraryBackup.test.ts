import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exportLibrary, importLibrary } from "./libraryBackup";

type FetchMock = ReturnType<typeof vi.fn>;

const originalFetch = globalThis.fetch;
const originalCreate = URL.createObjectURL;
const originalRevoke = URL.revokeObjectURL;

beforeEach(() => {
  // Fresh jsdom <body> for every test so the temporary anchor element we
  // create in exportLibrary doesn't leak between cases.
  document.body.innerHTML = "";
  URL.createObjectURL = vi.fn(() => "blob:mock");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
  vi.restoreAllMocks();
});

describe("exportLibrary", () => {
  it("downloads a date-stamped YAML file when the request succeeds", async () => {
    const mockFetch: FetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => "targets: []\n",
    }));
    globalThis.fetch = mockFetch as unknown as typeof fetch;

    // Spy on click so we can confirm the anchor is triggered.
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.setSystemTime(new Date("2026-03-14T12:34:56Z"));

    await exportLibrary();

    expect(mockFetch).toHaveBeenCalledWith("/api/library/export");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    // The Blob constructor receives ["targets: []\n"] — confirm the type
    // matches what Komga's importer accepts via the YAML helpers.
    const blob = (URL.createObjectURL as unknown as FetchMock).mock.calls[0][0] as Blob;
    expect(blob.type).toBe("application/yaml");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock");
    // The temporary anchor must not linger in the DOM after the download.
    expect(document.body.querySelector("a")).toBeNull();
  });

  it("uses the current UTC date in the filename", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => "x",
    })) as unknown as typeof fetch;
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-02T00:00:00Z"));

    let downloadName: string | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloadName = this.download;
    });

    await exportLibrary();
    expect(downloadName).toBe("gallery-dl-library-2026-01-02.yaml");
    vi.useRealTimers();
  });

  it("throws when the export endpoint returns an error", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 503,
      text: async () => "service unavailable",
    })) as unknown as typeof fetch;

    await expect(exportLibrary()).rejects.toThrow("HTTP 503");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("revokes the blob URL even when the click handler throws", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => "x",
    })) as unknown as typeof fetch;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
      throw new Error("popup blocked");
    });

    await expect(exportLibrary()).rejects.toThrow("popup blocked");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });
});

describe("importLibrary", () => {
  function fakeFile(content: string): File {
    return new File([content], "library.yaml", { type: "application/yaml" });
  }

  it("POSTs the file body as application/yaml and returns the parsed result", async () => {
    const payload = { imported: 3, updated: 1, errors: [] };
    const mockFetch: FetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }));
    globalThis.fetch = mockFetch as unknown as typeof fetch;

    const result = await importLibrary(fakeFile("targets:\n  - url: x\n"));

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/library/import");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "content-type": "application/yaml" });
    expect(init.body).toBe("targets:\n  - url: x\n");
    expect(result).toEqual(payload);
  });

  it("throws the server-provided body on a non-OK response", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      text: async () => "invalid yaml: line 3",
    })) as unknown as typeof fetch;

    await expect(importLibrary(fakeFile("nope"))).rejects.toThrow("invalid yaml: line 3");
  });

  it("falls back to HTTP <status> when the error body is empty", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 502,
      text: async () => "",
    })) as unknown as typeof fetch;

    await expect(importLibrary(fakeFile(""))).rejects.toThrow("HTTP 502");
  });
});
