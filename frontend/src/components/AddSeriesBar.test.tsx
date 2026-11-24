import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
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
import { AddSeriesBar } from "./AddSeriesBar";

afterEach(() => {
  vi.unstubAllGlobals();
});

const config = {
  postprocess_root: "/mnt/nas/Media",
  postprocess_default_output_dir: "/mnt/nas/Media/manga",
  postprocess_known_output_dirs: [],
  delete_raw_after_pack: true,
  default_watch_period: "1d",
  chapter_naming_template: "",
  default_reading_direction: "ltr",
};

function mockApi(postStatus = 200) {
  return mockFetch(async (input: FetchArgs[0], init?: FetchArgs[1]) => {
    const url = urlOf(input);
    if (url.includes("/api/output-dirs")) return jsonResponse([{ path: "/mnt/nas/Media/manga" }]);
    if (methodOf(input, init) === "POST") {
      return postStatus === 200
        ? jsonResponse({ id: 42, status: "pending" })
        : jsonResponse({ detail: "Unsupported URL" }, postStatus);
    }
    return jsonResponse(config);
  });
}

async function postBody(spy: ReturnType<typeof mockFetch>) {
  let call: FetchArgs | undefined;
  await waitFor(() => {
    call = findCall(spy, (i, init) => methodOf(i, init) === "POST");
    expect(call).toBeDefined();
  });
  const [input, init] = call as FetchArgs;
  return JSON.parse(await bodyOf(input, init));
}

describe("AddSeriesBar", () => {
  it("adds a URL with the configured defaults", async () => {
    const spy = mockApi();
    renderWithProviders(<AddSeriesBar />);
    // Wait for the default output dir to seed from config.
    await userEvent.click(screen.getByRole("button", { name: "Download options" }));
    const dir = (await screen.findByLabelText(/output directory/i, {
      selector: "input",
    })) as HTMLInputElement;
    await waitFor(() => expect(dir.value).toBe("/mnt/nas/Media/manga"));

    await userEvent.type(screen.getByLabelText("Gallery URL"), "  https://example/x  {Enter}");
    expect(await postBody(spy)).toEqual({
      url: "https://example/x",
      output_dir: "/mnt/nas/Media/manga",
      watched: false,
      tags: null,
      reading_direction: null,
    });
    await waitFor(() => expect(screen.getByLabelText("Gallery URL")).toHaveValue(""));
  });

  it("keeps the optional fields folded away until asked for", async () => {
    mockApi();
    renderWithProviders(<AddSeriesBar />);
    const toggle = screen.getByRole("button", { name: "Download options" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByLabelText("Watch for new chapters")).toBeInTheDocument();
  });

  it("sends watch and tags from the options", async () => {
    const spy = mockApi();
    renderWithProviders(<AddSeriesBar />);
    await userEvent.click(screen.getByRole("button", { name: "Download options" }));
    await userEvent.click(await screen.findByLabelText("Watch for new chapters"));
    await userEvent.type(screen.getByPlaceholderText("Enter to add"), "action{Enter}");
    await userEvent.type(screen.getByLabelText("Gallery URL"), "https://example/y");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await postBody(spy)).toMatchObject({ watched: true, tags: ["action"] });
  });

  it("asks for a URL before submitting, and shows server errors", async () => {
    mockApi(400);
    renderWithProviders(<AddSeriesBar />);
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByText("Enter a gallery URL.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Gallery URL"), "https://bad{Enter}");
    expect(await screen.findAllByText("Unsupported URL")).not.toHaveLength(0);
  });
});
