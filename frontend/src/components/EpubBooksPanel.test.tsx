import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EpubBookOut, EpubOverview } from "../api/types.gen";
import { bodyOf, findCall, jsonResponse, methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { EpubBooksPanel } from "./EpubBooksPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

function book(overrides: Partial<EpubBookOut>): EpubBookOut {
  return {
    id: 11,
    position: 1,
    title: "Series A, Vol. 1",
    custom_title: null,
    chapter_start: 1,
    chapter_end: 2,
    chapter_count: 2,
    page_count: 40,
    first_chapter: "1",
    last_chapter: "2",
    status: "not_exported",
    exported_at: null,
    file_name: null,
    ...overrides,
  };
}

function overview(overrides: Partial<EpubOverview> = {}): EpubOverview {
  const chapters = ["1", "2", "3"].map((number) => ({
    number,
    title: "",
    volume: number === "3" ? "2" : "1",
    pages: 20,
    file_name: `Series A - c${number}.cbz`,
    book_position: null,
  }));
  return {
    target_id: 1,
    series: "Series A",
    series_dir: "/media/manga/Series A",
    export_dir: "/data/epub",
    chapters,
    books: [],
    unassigned: ["1", "2", "3"],
    suggested_books: [
      { title: null, chapter_start: 1, chapter_end: 2 },
      { title: null, chapter_start: 3, chapter_end: null },
    ],
    ...overrides,
  };
}

function mockEpub(initial: EpubOverview, onPut?: (body: unknown) => EpubOverview) {
  let current = initial;
  return mockFetch(async (input, init) => {
    const url = urlOf(input);
    const method = methodOf(input, init);
    if (url.endsWith("/epub/books") && method === "PUT") {
      const body = JSON.parse(await bodyOf(input, init));
      current = onPut ? onPut(body) : current;
      return jsonResponse(current);
    }
    if (url.includes("/epub/books/") && url.endsWith("/export")) {
      current = {
        ...current,
        books: current.books.map((b) => ({
          ...b,
          status: "exported" as const,
          file_name: "Series A - Vol. 01.epub",
          exported_at: "2026-11-23T10:00:00+00:00",
        })),
      };
      return jsonResponse(current);
    }
    if (url.endsWith("/epub/export")) {
      return jsonResponse({ exported: 1, failed: 0, errors: [] });
    }
    if (url.endsWith("/epub")) return jsonResponse(current);
    return jsonResponse({}, 404);
  });
}

async function openPanel() {
  await userEvent.click(screen.getByRole("button", { name: "Manage" }));
}

describe("EpubBooksPanel", () => {
  it("does not fetch until opened", async () => {
    const spy = mockEpub(overview());
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    expect(spy).not.toHaveBeenCalled();

    await openPanel();
    expect(await screen.findByText(/3 chapters on disk/)).toBeInTheDocument();
    expect(screen.getByText("/data/epub")).toBeInTheDocument();
    expect(screen.getByText(/Not in any book \(3\)/)).toBeInTheDocument();
  });

  it("fills rows from volumes and saves them", async () => {
    const spy = mockEpub(overview(), () =>
      overview({
        books: [
          book({ id: 11, position: 1, chapter_start: 1, chapter_end: 2 }),
          book({
            id: 12,
            position: 2,
            title: "Series A, Vol. 2",
            chapter_start: 3,
            chapter_end: null,
            chapter_count: 1,
            first_chapter: "3",
            last_chapter: "3",
          }),
        ],
        unassigned: [],
      }),
    );
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Use volumes (2)" }));
    const starts = screen.getAllByLabelText("From chapter") as HTMLInputElement[];
    expect(starts.map((i) => i.value)).toEqual(["1", "3"]);
    const titles = screen.getAllByLabelText("Title") as HTMLInputElement[];
    expect(titles[1].placeholder).toBe("Series A, Vol. 2");
    await userEvent.type(titles[0], "Prologue");

    await userEvent.click(screen.getByRole("button", { name: "Save books" }));

    await waitFor(() => {
      expect(findCall(spy, (i, init) => methodOf(i, init) === "PUT")).toBeDefined();
    });
    const [putInput, putInit] = findCall(spy, (i, init) => methodOf(i, init) === "PUT") ?? [];
    expect(JSON.parse(await bodyOf(putInput as RequestInfo, putInit))).toEqual({
      books: [
        { title: "Prologue", chapter_start: 1, chapter_end: 2 },
        { title: null, chapter_start: 3, chapter_end: null },
      ],
    });
    // Saved: per-book status + export actions appear.
    expect(await screen.findAllByText("not exported")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Export 2 pending" })).toBeInTheDocument();
  });

  it("validates bounds locally before saving", async () => {
    const spy = mockEpub(overview());
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Add book" }));
    const start = screen.getByLabelText("From chapter") as HTMLInputElement;
    expect(start.value).toBe("1");
    await userEvent.clear(start);
    await userEvent.click(screen.getByRole("button", { name: "Save books" }));

    expect(
      await screen.findByText("Book 1: enter the chapter number it starts at."),
    ).toBeInTheDocument();
    expect(findCall(spy, (i, init) => methodOf(i, init) === "PUT")).toBeUndefined();
  });

  it("shows server validation errors", async () => {
    mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        return jsonResponse({ detail: "books overlap: chapter 2 is already in a book" }, 400);
      }
      return jsonResponse(overview());
    });
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    await openPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Use volumes (2)" }));
    await userEvent.click(screen.getByRole("button", { name: "Save books" }));
    expect(await screen.findByText(/books overlap/)).toBeInTheDocument();
  });

  it("exports a book and then offers its download", async () => {
    const spy = mockEpub(overview({ books: [book({})], unassigned: ["3"] }));
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Export" }));

    await waitFor(() => {
      expect(
        findCall(spy, (i) => urlOf(i).endsWith("/api/targets/1/epub/books/11/export")),
      ).toBeDefined();
    });
    const link = await screen.findByRole("link", { name: /download/i });
    expect(link).toHaveAttribute("href", "/api/targets/1/epub/books/11/file");
    expect(link).toHaveAttribute("download", "Series A - Vol. 01.epub");
    expect(screen.getByText("exported")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-export" })).toBeInTheDocument();
  });

  it("disables export for a book with no chapters on disk", async () => {
    mockEpub(overview({ books: [book({ status: "empty", chapter_count: 0 })] }));
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    await openPanel();
    expect(await screen.findByRole("button", { name: "Export" })).toBeDisabled();
    expect(screen.getByText("no chapters")).toBeInTheDocument();
  });

  it("explains when the series has not been downloaded", async () => {
    mockEpub(overview({ series: null, series_dir: null, chapters: [], suggested_books: [] }));
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    await openPanel();
    expect(await screen.findByText(/hasn't been downloaded yet/)).toBeInTheDocument();
  });

  it("discards local edits", async () => {
    mockEpub(overview({ books: [book({})] }));
    renderWithProviders(<EpubBooksPanel targetId={1} />);
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Remove book 1" }));
    expect(screen.queryByLabelText("From chapter")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect((screen.getByLabelText("From chapter") as HTMLInputElement).value).toBe("1");
  });
});
