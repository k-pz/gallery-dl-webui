import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { SubmitForm } from "./SubmitForm";

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

const downloadStub = {
  id: 42,
  url: "https://example/x",
  extractor: "fake",
  status: "pending",
  created_at: "now",
  started_at: null,
  finished_at: null,
  exit_code: null,
  files_downloaded: 0,
  files_expected: null,
  error: null,
  postprocess_status: null,
  postprocess_chapters_packed: null,
  postprocess_error: null,
  output_dir: null,
};

const noRootConfig = {
  postprocess_root: null,
  postprocess_default_output_dir: null,
  postprocess_known_output_dirs: [],
  delete_raw_after_pack: true,
};

const withRootConfig = {
  postprocess_root: "/mnt/nas/Media",
  postprocess_default_output_dir: "/mnt/nas/Media/manga",
  postprocess_known_output_dirs: ["/mnt/nas/Media/comics"],
  delete_raw_after_pack: true,
};

describe("SubmitForm", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("submits with a null output_dir when no root is configured", async () => {
    const onCreated = vi.fn();
    const fetchSpy = mockFetch(async (input, init) => {
      if (methodOf(input, init) === "POST") return jsonResponse(downloadStub);
      return jsonResponse(noRootConfig);
    });

    renderWithProviders(<SubmitForm onCreated={onCreated} />);
    const input = screen.getByLabelText(/gallery url/i);
    await userEvent.type(input, "  https://example/x  ");
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
    const postCall = findCall(fetchSpy, "POST");
    expect(postCall).toBeDefined();
    const [postInput, postInit] = postCall as FetchArgs;
    expect(JSON.parse(await bodyOf(postInput, postInit))).toEqual({
      url: "https://example/x",
      output_dir: null,
    });
  });

  it("seeds the output-dir field from the configured default", async () => {
    mockFetch(async (input, init) => {
      if (methodOf(input, init) === "POST") return jsonResponse(downloadStub);
      return jsonResponse(withRootConfig);
    });

    renderWithProviders(<SubmitForm onCreated={vi.fn()} />);

    const dirInput = (await screen.findByRole("combobox", {
      name: /output directory/i,
    })) as HTMLInputElement;
    await waitFor(() => expect(dirInput.value).toBe("/mnt/nas/Media/manga"));
  });

  it("submits the typed output_dir verbatim", async () => {
    const fetchSpy = mockFetch(async (input, init) => {
      if (methodOf(input, init) === "POST") return jsonResponse(downloadStub);
      return jsonResponse(withRootConfig);
    });

    renderWithProviders(<SubmitForm onCreated={vi.fn()} />);
    const urlInput = screen.getByLabelText(/gallery url/i);
    await userEvent.type(urlInput, "https://example/x");

    const dirInput = (await screen.findByRole("combobox", {
      name: /output directory/i,
    })) as HTMLInputElement;
    fireEvent.change(dirInput, { target: { value: "/mnt/nas/Media/webtoons" } });
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    let postCall: FetchArgs | undefined;
    await waitFor(() => {
      postCall = findCall(fetchSpy, "POST");
      expect(postCall).toBeDefined();
    });
    const [postInput, postInit] = postCall as FetchArgs;
    expect(JSON.parse(await bodyOf(postInput, postInit))).toEqual({
      url: "https://example/x",
      output_dir: "/mnt/nas/Media/webtoons",
    });
  });

  it("disables the output-dir field until root is configured", async () => {
    mockFetch(async () => jsonResponse(noRootConfig));

    renderWithProviders(<SubmitForm onCreated={vi.fn()} />);

    const dirInput = (await screen.findByRole("combobox", {
      name: /output directory/i,
    })) as HTMLInputElement;
    expect(dirInput).toBeDisabled();
  });

  it("shows a local error when submitting an empty URL", async () => {
    const onCreated = vi.fn();
    const fetchSpy = mockFetch(async () => jsonResponse(noRootConfig));

    renderWithProviders(<SubmitForm onCreated={onCreated} />);
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    expect(await screen.findByText(/url is required/i)).toBeInTheDocument();
    // Only the config GET should have happened — no POST.
    expect(findCall(fetchSpy, "POST")).toBeUndefined();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("renders the server-side detail when the request fails", async () => {
    mockFetch(async (input, init) => {
      if (methodOf(input, init) === "POST") {
        return jsonResponse({ detail: "unsupported URL (no gallery-dl extractor matched)" }, 400);
      }
      return jsonResponse(noRootConfig);
    });

    renderWithProviders(<SubmitForm onCreated={vi.fn()} />);
    await userEvent.type(screen.getByLabelText(/gallery url/i), "https://example/nope");
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    expect(await screen.findByText(/unsupported url/i)).toBeInTheDocument();
  });
});
