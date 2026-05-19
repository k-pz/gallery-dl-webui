import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  bodyOf,
  type FetchArgs,
  findCall,
  jsonResponse,
  methodOf,
  mockFetch,
  urlOf,
} from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { SubmitForm } from "./SubmitForm";

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
  target_id: 7,
};

type ConfigShape = {
  postprocess_root: string | null;
  postprocess_default_output_dir: string | null;
  postprocess_known_output_dirs: string[];
  delete_raw_after_pack: boolean;
  default_watch_period: string;
};

const noRootConfig: ConfigShape = {
  postprocess_root: null,
  postprocess_default_output_dir: null,
  postprocess_known_output_dirs: [],
  delete_raw_after_pack: true,
  default_watch_period: "1d",
};

const withRootConfig: ConfigShape = {
  postprocess_root: "/mnt/nas/Media",
  postprocess_default_output_dir: "/mnt/nas/Media/manga",
  postprocess_known_output_dirs: ["/mnt/nas/Media/comics"],
  delete_raw_after_pack: true,
  default_watch_period: "1d",
};

function makeHandler(config: ConfigShape, outputDirs: { path: string }[] = []) {
  return async (input: FetchArgs[0], init?: FetchArgs[1]) => {
    const u = urlOf(input);
    if (u.includes("/api/output-dirs")) return jsonResponse(outputDirs);
    if (methodOf(input, init) === "POST") return jsonResponse(downloadStub);
    return jsonResponse(config);
  };
}

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
    const fetchSpy = mockFetch(makeHandler(noRootConfig));

    renderWithProviders(<SubmitForm onCreated={onCreated} />);
    const input = screen.getByLabelText(/gallery url/i);
    await userEvent.type(input, "  https://example/x  ");
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
    const postCall = findCall(fetchSpy, (i, init) => methodOf(i, init) === "POST");
    expect(postCall).toBeDefined();
    const [postInput, postInit] = postCall as FetchArgs;
    expect(JSON.parse(await bodyOf(postInput, postInit))).toEqual({
      url: "https://example/x",
      output_dir: null,
    });
  });

  it("seeds the picker from the configured default and submits it", async () => {
    const fetchSpy = mockFetch(
      makeHandler(withRootConfig, [
        { path: "/mnt/nas/Media/manga" },
        { path: "/mnt/nas/Media/comics" },
      ]),
    );

    renderWithProviders(<SubmitForm onCreated={vi.fn()} />);

    const dirInput = (await screen.findByLabelText(/output directory/i, {
      selector: "input",
    })) as HTMLInputElement;
    await waitFor(() => expect(dirInput.value).toBe("/mnt/nas/Media/manga"));

    await userEvent.type(screen.getByLabelText(/gallery url/i), "https://example/x");
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    let postCall: FetchArgs | undefined;
    await waitFor(() => {
      postCall = findCall(fetchSpy, (i, init) => methodOf(i, init) === "POST");
      expect(postCall).toBeDefined();
    });
    const [postInput, postInit] = postCall as FetchArgs;
    expect(JSON.parse(await bodyOf(postInput, postInit))).toEqual({
      url: "https://example/x",
      output_dir: "/mnt/nas/Media/manga",
    });
  });

  it("disables the output-dir picker until root is configured", async () => {
    mockFetch(makeHandler(noRootConfig));

    renderWithProviders(<SubmitForm onCreated={vi.fn()} />);

    const dirInput = (await screen.findByLabelText(/output directory/i, {
      selector: "input",
    })) as HTMLInputElement;
    expect(dirInput).toBeDisabled();
  });

  it("shows a local error when submitting an empty URL", async () => {
    const onCreated = vi.fn();
    const fetchSpy = mockFetch(makeHandler(noRootConfig));

    renderWithProviders(<SubmitForm onCreated={onCreated} />);
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    expect(await screen.findByText(/url is required/i)).toBeInTheDocument();
    expect(findCall(fetchSpy, (i, init) => methodOf(i, init) === "POST")).toBeUndefined();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("renders the server-side detail when the request fails", async () => {
    mockFetch(async (input, init) => {
      const u = urlOf(input);
      if (u.includes("/api/output-dirs")) return jsonResponse([]);
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
