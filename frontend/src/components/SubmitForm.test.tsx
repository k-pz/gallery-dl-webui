import { screen, waitFor } from "@testing-library/react";
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

describe("SubmitForm", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("submits the trimmed URL and calls onCreated with the new id", async () => {
    const onCreated = vi.fn();
    mockFetch(async () =>
      jsonResponse({
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
      }),
    );

    renderWithProviders(<SubmitForm onCreated={onCreated} />);
    const input = screen.getByLabelText(/gallery url/i);
    await userEvent.type(input, "  https://example/x  ");
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42));
  });

  it("shows a local error when submitting an empty URL", async () => {
    const onCreated = vi.fn();
    const fetchSpy = mockFetch(async () => jsonResponse({}));

    renderWithProviders(<SubmitForm onCreated={onCreated} />);
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    expect(await screen.findByText(/url is required/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("renders the server-side detail when the request fails", async () => {
    mockFetch(async () =>
      jsonResponse({ detail: "unsupported URL (no gallery-dl extractor matched)" }, 400),
    );

    renderWithProviders(<SubmitForm onCreated={vi.fn()} />);
    await userEvent.type(screen.getByLabelText(/gallery url/i), "https://example/nope");
    await userEvent.click(screen.getByRole("button", { name: /download/i }));

    expect(await screen.findByText(/unsupported url/i)).toBeInTheDocument();
  });
});
