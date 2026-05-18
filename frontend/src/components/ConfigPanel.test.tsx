import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { ConfigPanel } from "./ConfigPanel";

type FetchArgs = Parameters<typeof fetch>;

function mockFetch(
  handler: (input: FetchArgs[0], init?: FetchArgs[1]) => Response | Promise<Response>,
) {
  const spy = vi.fn(handler);
  vi.stubGlobal("fetch", spy);
  return spy;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function methodOf(input: FetchArgs[0], init?: FetchArgs[1]): string {
  if (input instanceof Request) return input.method;
  return init?.method ?? "GET";
}

async function bodyOf(input: FetchArgs[0], init?: FetchArgs[1]): Promise<string> {
  if (input instanceof Request) return await input.clone().text();
  return String(init?.body ?? "");
}

function findCall(spy: ReturnType<typeof mockFetch>, method: string): FetchArgs | undefined {
  return spy.mock.calls.find(([input, init]) => methodOf(input, init) === method);
}

describe("ConfigPanel", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the loaded config", async () => {
    mockFetch(async () =>
      jsonResponse({
        postprocess_output_dir: "/mnt/manga",
        delete_raw_after_pack: true,
      }),
    );

    renderWithProviders(<ConfigPanel />);

    const input = (await screen.findByLabelText(/output directory/i)) as HTMLInputElement;
    expect(input.value).toBe("/mnt/manga");
    expect(screen.getByLabelText(/delete raw images after packing/i)).toBeChecked();
  });

  it("disables Save until a field changes", async () => {
    mockFetch(async () =>
      jsonResponse({
        postprocess_output_dir: null,
        delete_raw_after_pack: true,
      }),
    );

    renderWithProviders(<ConfigPanel />);

    const input = (await screen.findByLabelText(/output directory/i)) as HTMLInputElement;
    const save = screen.getByRole("button", { name: /save/i });
    expect(save).toBeDisabled();

    fireEvent.change(input, { target: { value: "/tmp/out" } });
    await waitFor(() => expect(save).not.toBeDisabled());
  });

  it("submits the new config and shows a saved indicator", async () => {
    let stored: unknown = { postprocess_output_dir: null, delete_raw_after_pack: true };
    const fetchSpy = mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        stored = JSON.parse(await bodyOf(input, init));
        return jsonResponse(stored);
      }
      return jsonResponse(stored);
    });

    renderWithProviders(<ConfigPanel />);

    const input = (await screen.findByLabelText(/output directory/i)) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "/tmp/out" } });
    const save = screen.getByRole("button", { name: /save/i });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    let putCall: FetchArgs | undefined;
    await waitFor(() => {
      putCall = findCall(fetchSpy, "PUT");
      expect(putCall).toBeDefined();
    });
    const [putInput, putInit] = putCall as FetchArgs;
    expect(JSON.parse(await bodyOf(putInput, putInit))).toEqual({
      postprocess_output_dir: "/tmp/out",
      delete_raw_after_pack: true,
    });
    await screen.findByText(/saved/i);
  });

  it("surfaces a server-side error from PUT", async () => {
    mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        return jsonResponse({ detail: "postprocess_output_dir must be an absolute path" }, 400);
      }
      return jsonResponse({
        postprocess_output_dir: null,
        delete_raw_after_pack: true,
      });
    });

    renderWithProviders(<ConfigPanel />);

    const input = (await screen.findByLabelText(/output directory/i)) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "relative/dir" } });
    const save = screen.getByRole("button", { name: /save/i });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    await waitFor(() => expect(screen.getByText(/absolute path/i)).toBeInTheDocument());
  });

  it("sends null when the path field is cleared", async () => {
    let stored: unknown = { postprocess_output_dir: "/old", delete_raw_after_pack: true };
    const fetchSpy = mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        stored = JSON.parse(await bodyOf(input, init));
        return jsonResponse(stored);
      }
      return jsonResponse(stored);
    });

    renderWithProviders(<ConfigPanel />);

    const input = (await screen.findByLabelText(/output directory/i)) as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("/old"));
    fireEvent.change(input, { target: { value: "" } });
    const save = screen.getByRole("button", { name: /save/i });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    let putCall: FetchArgs | undefined;
    await waitFor(() => {
      putCall = findCall(fetchSpy, "PUT");
      expect(putCall).toBeDefined();
    });
    const [putInput, putInit] = putCall as FetchArgs;
    expect(JSON.parse(await bodyOf(putInput, putInit))).toEqual({
      postprocess_output_dir: null,
      delete_raw_after_pack: true,
    });
  });
});
