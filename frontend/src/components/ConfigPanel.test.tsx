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

const emptyConfig = {
  postprocess_root: null,
  postprocess_default_output_dir: null,
  postprocess_known_output_dirs: [],
  delete_raw_after_pack: true,
};

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
        postprocess_root: "/mnt/nas/Media",
        postprocess_default_output_dir: "/mnt/nas/Media/manga",
        postprocess_known_output_dirs: ["/mnt/nas/Media/comics"],
        delete_raw_after_pack: true,
      }),
    );

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    expect(rootInput.value).toBe("/mnt/nas/Media");
    const defaultInput = screen.getByLabelText(/default output directory/i) as HTMLInputElement;
    expect(defaultInput.value).toBe("/mnt/nas/Media/manga");
    expect(screen.getByLabelText(/delete raw images after packing/i)).toBeChecked();
    expect(screen.getByText("/mnt/nas/Media/comics")).toBeInTheDocument();
  });

  it("disables Save until a field changes", async () => {
    mockFetch(async () => jsonResponse(emptyConfig));

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    const save = screen.getByRole("button", { name: /save/i });
    expect(save).toBeDisabled();

    fireEvent.change(rootInput, { target: { value: "/mnt/nas/Media" } });
    await waitFor(() => expect(save).not.toBeDisabled());
  });

  it("submits the new config", async () => {
    let stored = emptyConfig;
    const fetchSpy = mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        const body = JSON.parse(await bodyOf(input, init));
        stored = { ...stored, ...body };
        return jsonResponse(stored);
      }
      return jsonResponse(stored);
    });

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    fireEvent.change(rootInput, { target: { value: "/mnt/nas/Media" } });
    const defaultInput = screen.getByLabelText(/default output directory/i) as HTMLInputElement;
    fireEvent.change(defaultInput, { target: { value: "/mnt/nas/Media/manga" } });
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
      postprocess_root: "/mnt/nas/Media",
      postprocess_default_output_dir: "/mnt/nas/Media/manga",
      delete_raw_after_pack: true,
    });
    await screen.findByText(/saved/i);
  });

  it("surfaces a server-side error from PUT", async () => {
    mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        return jsonResponse({ detail: "postprocess_root must be an absolute path" }, 400);
      }
      return jsonResponse(emptyConfig);
    });

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    fireEvent.change(rootInput, { target: { value: "relative/dir" } });
    const save = screen.getByRole("button", { name: /save/i });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    await waitFor(() => expect(screen.getByText(/absolute path/i)).toBeInTheDocument());
  });

  it("disables the default-dir input until root is set", async () => {
    mockFetch(async () => jsonResponse(emptyConfig));

    renderWithProviders(<ConfigPanel />);

    const defaultInput = (await screen.findByLabelText(
      /default output directory/i,
    )) as HTMLInputElement;
    expect(defaultInput).toBeDisabled();

    const rootInput = screen.getByLabelText(/^root$/i) as HTMLInputElement;
    fireEvent.change(rootInput, { target: { value: "/mnt/nas/Media" } });
    await waitFor(() => expect(defaultInput).not.toBeDisabled());
  });

  it("sends null when both path fields are cleared", async () => {
    let stored: unknown = {
      postprocess_root: "/old",
      postprocess_default_output_dir: "/old/manga",
      postprocess_known_output_dirs: [],
      delete_raw_after_pack: true,
    };
    const fetchSpy = mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        const body = JSON.parse(await bodyOf(input, init));
        stored = { ...(stored as object), ...body };
        return jsonResponse(stored);
      }
      return jsonResponse(stored);
    });

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    await waitFor(() => expect(rootInput.value).toBe("/old"));
    const defaultInput = screen.getByLabelText(/default output directory/i) as HTMLInputElement;
    fireEvent.change(defaultInput, { target: { value: "" } });
    fireEvent.change(rootInput, { target: { value: "" } });
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
      postprocess_root: null,
      postprocess_default_output_dir: null,
      delete_raw_after_pack: true,
    });
  });
});
