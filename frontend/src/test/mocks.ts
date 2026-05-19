import { type Mock, vi } from "vitest";

export type FetchArgs = Parameters<typeof fetch>;
export type FetchHandler = (
  input: FetchArgs[0],
  init?: FetchArgs[1],
) => Response | Promise<Response>;
export type FetchSpy = Mock<FetchHandler>;

export function mockFetch(handler: FetchHandler): FetchSpy {
  const spy = vi.fn(handler);
  vi.stubGlobal("fetch", spy);
  return spy;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function methodOf(input: FetchArgs[0], init?: FetchArgs[1]): string {
  if (input instanceof Request) return input.method;
  return init?.method ?? "GET";
}

export function urlOf(input: FetchArgs[0]): string {
  if (input instanceof Request) return input.url;
  if (input instanceof URL) return input.toString();
  return String(input);
}

export async function bodyOf(input: FetchArgs[0], init?: FetchArgs[1]): Promise<string> {
  if (input instanceof Request) return await input.clone().text();
  return String(init?.body ?? "");
}

export function findCall(
  spy: FetchSpy,
  predicate: (input: FetchArgs[0], init?: FetchArgs[1]) => boolean,
): FetchArgs | undefined {
  return spy.mock.calls.find(([input, init]) => predicate(input, init));
}
