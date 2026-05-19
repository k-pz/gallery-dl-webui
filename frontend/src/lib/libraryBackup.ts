import type { LibraryImportResult } from "../api/types.gen";

/**
 * The YAML library export/import endpoints exchange `application/yaml`, which
 * the generated openapi-ts client doesn't model natively. These helpers wrap
 * the raw fetch calls so the component layer only deals with success/error.
 */

export async function exportLibrary(): Promise<void> {
  const resp = await fetch("/api/library/export");
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const text = await resp.text();
  const blob = new Blob([text], { type: "application/yaml" });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `gallery-dl-library-${stamp}.yaml`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function importLibrary(file: File): Promise<LibraryImportResult> {
  const text = await file.text();
  const resp = await fetch("/api/library/import", {
    method: "POST",
    headers: { "content-type": "application/yaml" },
    body: text,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(body || `HTTP ${resp.status}`);
  }
  return (await resp.json()) as LibraryImportResult;
}
