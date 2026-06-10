import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { listDownloadsQueryKey, listTargetsQueryKey } from "../api/@tanstack/react-query.gen";
import { client } from "../api/client.gen";
import { installResponseEventInterceptor } from "./responseEventInterceptor";

function setup() {
  const qc = new QueryClient();
  const invalidated: unknown[] = [];
  vi.spyOn(qc, "invalidateQueries").mockImplementation(((filters: { queryKey?: unknown }) => {
    invalidated.push(filters?.queryKey);
    return Promise.resolve();
  }) as typeof qc.invalidateQueries);
  const eject = installResponseEventInterceptor(qc);
  return { qc, invalidated, eject };
}

async function runInterceptors(response: Response): Promise<Response> {
  // Drive the generated client's response interceptor chain directly.
  let out = response;
  // biome-ignore lint/suspicious/noExplicitAny: reaching into the generated client's interceptor internals for the test
  for (const fn of (client.interceptors.response as any).fns as Array<
    ((r: Response) => Response | Promise<Response>) | null
  >) {
    if (fn) out = await fn(out);
  }
  return out;
}

describe("installResponseEventInterceptor", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("dispatches events from the X-Events header", async () => {
    const { invalidated, eject } = setup();
    try {
      const events = [{ topic: "downloads", type: "updated", data: {} }];
      await runInterceptors(
        new Response("{}", { headers: { "X-Events": JSON.stringify(events) } }),
      );
      expect(invalidated).toEqual([listDownloadsQueryKey(), listTargetsQueryKey()]);
    } finally {
      eject();
    }
  });

  it("ignores responses without the header and malformed payloads", async () => {
    const { invalidated, eject } = setup();
    try {
      await runInterceptors(new Response("{}"));
      await runInterceptors(new Response("{}", { headers: { "X-Events": "not json" } }));
      await runInterceptors(new Response("{}", { headers: { "X-Events": '{"topic":1}' } }));
      expect(invalidated).toEqual([]);
    } finally {
      eject();
    }
  });

  it("eject removes the handler", async () => {
    const { invalidated, eject } = setup();
    eject();
    const events = [{ topic: "downloads", type: "updated", data: {} }];
    await runInterceptors(new Response("{}", { headers: { "X-Events": JSON.stringify(events) } }));
    expect(invalidated).toEqual([]);
  });
});
