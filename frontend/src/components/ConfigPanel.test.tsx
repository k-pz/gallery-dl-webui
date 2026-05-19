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

function urlOf(input: FetchArgs[0]): string {
  if (input instanceof Request) return input.url;
  if (input instanceof URL) return input.toString();
  return String(input);
}

async function bodyOf(input: FetchArgs[0], init?: FetchArgs[1]): Promise<string> {
  if (input instanceof Request) return await input.clone().text();
  return String(init?.body ?? "");
}

function findCall(
  spy: ReturnType<typeof mockFetch>,
  predicate: (input: FetchArgs[0], init?: FetchArgs[1]) => boolean,
): FetchArgs | undefined {
  return spy.mock.calls.find(([input, init]) => predicate(input, init));
}

type ConfigShape = {
  postprocess_root: string | null;
  postprocess_default_output_dir: string | null;
  postprocess_known_output_dirs: string[];
  delete_raw_after_pack: boolean;
  default_watch_period: string;
};

const emptyConfig: ConfigShape = {
  postprocess_root: null,
  postprocess_default_output_dir: null,
  postprocess_known_output_dirs: [],
  delete_raw_after_pack: true,
  default_watch_period: "1d",
};

function configHandler(state: { current: ConfigShape }) {
  return async (input: FetchArgs[0], init?: FetchArgs[1]) => {
    const u = urlOf(input);
    if (u.includes("/api/output-dirs")) return jsonResponse([]);
    if (methodOf(input, init) === "PUT") {
      const body = JSON.parse(await bodyOf(input, init));
      state.current = { ...state.current, ...body };
      return jsonResponse(state.current);
    }
    return jsonResponse(state.current);
  };
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
    mockFetch(async (input) => {
      const u = urlOf(input);
      if (u.includes("/api/output-dirs")) return jsonResponse([]);
      return jsonResponse({
        postprocess_root: "/mnt/nas/Media",
        postprocess_default_output_dir: "/mnt/nas/Media/manga",
        postprocess_known_output_dirs: ["/mnt/nas/Media/comics"],
        delete_raw_after_pack: true,
        default_watch_period: "2h",
      });
    });

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    expect(rootInput.value).toBe("/mnt/nas/Media");
    const defaultInput = (await screen.findByLabelText(/default output directory/i, {
      selector: "input",
    })) as HTMLInputElement;
    await waitFor(() => expect(defaultInput.value).toBe("/mnt/nas/Media/manga"));
    expect(screen.getByLabelText(/delete raw images after packing/i)).toBeChecked();
    const periodInput = screen.getByLabelText(/default poll period/i) as HTMLInputElement;
    expect(periodInput.value).toBe("2h");
    expect(screen.getByText("/mnt/nas/Media/comics")).toBeInTheDocument();
  });

  it("disables Save until a field changes", async () => {
    const state = { current: { ...emptyConfig } };
    mockFetch(configHandler(state));

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    const save = screen.getByRole("button", { name: /save/i });
    expect(save).toBeDisabled();

    fireEvent.change(rootInput, { target: { value: "/mnt/nas/Media" } });
    await waitFor(() => expect(save).not.toBeDisabled());
  });

  it("submits the new config", async () => {
    const state = { current: { ...emptyConfig } };
    const fetchSpy = mockFetch(configHandler(state));

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    fireEvent.change(rootInput, { target: { value: "/mnt/nas/Media" } });
    const save = screen.getByRole("button", { name: /save/i });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    let putCall: FetchArgs | undefined;
    await waitFor(() => {
      putCall = findCall(fetchSpy, (i, init) => methodOf(i, init) === "PUT");
      expect(putCall).toBeDefined();
    });
    const [putInput, putInit] = putCall as FetchArgs;
    expect(JSON.parse(await bodyOf(putInput, putInit))).toEqual({
      postprocess_root: "/mnt/nas/Media",
      postprocess_default_output_dir: null,
      delete_raw_after_pack: true,
      default_watch_period: "1d",
    });
    await screen.findByText(/saved/i);
  });

  it("surfaces a server-side error from PUT", async () => {
    mockFetch(async (input, init) => {
      const u = urlOf(input);
      if (u.includes("/api/output-dirs")) return jsonResponse([]);
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

  it("disables the default-dir picker until root is set", async () => {
    mockFetch(async (input) => {
      const u = urlOf(input);
      if (u.includes("/api/output-dirs")) return jsonResponse([]);
      return jsonResponse(emptyConfig);
    });

    renderWithProviders(<ConfigPanel />);

    const defaultInput = (await screen.findByLabelText(/default output directory/i, {
      selector: "input",
    })) as HTMLInputElement;
    expect(defaultInput).toBeDisabled();

    const rootInput = screen.getByLabelText(/^root$/i) as HTMLInputElement;
    fireEvent.change(rootInput, { target: { value: "/mnt/nas/Media" } });
    await waitFor(() => expect(defaultInput).not.toBeDisabled());
  });

  it("persists theme choice in localStorage and applies it to <html>", async () => {
    mockFetch(async (input) => {
      const u = urlOf(input);
      if (u.includes("/api/output-dirs")) return jsonResponse([]);
      return jsonResponse(emptyConfig);
    });
    window.localStorage.removeItem("mantine-color-scheme-value");

    renderWithProviders(<ConfigPanel />);

    const segment = (await screen.findByRole("radiogroup", {
      name: /theme/i,
    })) as HTMLElement;
    fireEvent.click(screen.getByRole("radio", { name: /^dark$/i }));

    await waitFor(() => {
      expect(window.localStorage.getItem("mantine-color-scheme-value")).toBe("dark");
    });
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("dark");
    });
    expect(segment).toBeInTheDocument();
  });

  it("sends null root when the field is cleared", async () => {
    const state: { current: ConfigShape } = {
      current: {
        postprocess_root: "/old",
        postprocess_default_output_dir: null,
        postprocess_known_output_dirs: [],
        delete_raw_after_pack: true,
        default_watch_period: "1d",
      },
    };
    const fetchSpy = mockFetch(configHandler(state));

    renderWithProviders(<ConfigPanel />);

    const rootInput = (await screen.findByLabelText(/^root$/i)) as HTMLInputElement;
    await waitFor(() => expect(rootInput.value).toBe("/old"));
    fireEvent.change(rootInput, { target: { value: "" } });
    const save = screen.getByRole("button", { name: /save/i });
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    let putCall: FetchArgs | undefined;
    await waitFor(() => {
      putCall = findCall(fetchSpy, (i, init) => methodOf(i, init) === "PUT");
      expect(putCall).toBeDefined();
    });
    const [putInput, putInit] = putCall as FetchArgs;
    expect(JSON.parse(await bodyOf(putInput, putInit))).toEqual({
      postprocess_root: null,
      postprocess_default_output_dir: null,
      delete_raw_after_pack: true,
      default_watch_period: "1d",
    });
  });
});
