import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EpubBookOut, EpubOverview } from "../api/types.gen";
import { bodyOf, findCall, jsonResponse, methodOf, mockFetch, urlOf } from "../test/mocks";
import { renderWithProviders } from "../test/render";
import { clearPackerDrafts, EpubPacker } from "./EpubPacker";

afterEach(() => {
  vi.unstubAllGlobals();
  clearPackerDrafts();
});

function book(overrides: Partial<EpubBookOut>): EpubBookOut {
  return {
    id: 11,
    position: 1,
    title: "Series A, Vol. 1",
    custom_title: null,
    chapter_start: 1,
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
  const chapters = ["1", "2", "3", "4"].map((number) => ({
    number,
    title: `Title ${number}`,
    volume: Number(number) <= 2 ? "1" : "",
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
    unassigned: ["1", "2", "3", "4"],
    suggested_books: [
      { title: null, chapter_start: 1 },
      { title: null, chapter_start: 3 },
    ],
    ...overrides,
  };
}

/** Saved books for starts [1, 3] over chapters 1–4. */
const SAVED = [
  book({ id: 11, chapter_start: 1, status: "exported", file_name: "Series A - Vol. 01.epub" }),
  book({
    id: 12,
    position: 2,
    title: "Series A, Vol. 2",
    chapter_start: 3,
    first_chapter: "3",
    last_chapter: "4",
  }),
];

function mockEpub(initial: EpubOverview) {
  let current = initial;
  return mockFetch(async (input, init) => {
    const url = urlOf(input);
    const method = methodOf(input, init);
    if (url.endsWith("/epub/books") && method === "PUT") {
      const body = JSON.parse(await bodyOf(input, init)) as {
        books: { chapter_start: number; title: string | null }[];
      };
      current = {
        ...current,
        books: body.books.map((b, i) =>
          book({ id: 100 + i, position: i + 1, chapter_start: b.chapter_start }),
        ),
      };
      return jsonResponse(current);
    }
    if (url.endsWith("/epub/export")) return jsonResponse({ exported: 1, failed: 0, errors: [] });
    if (url.endsWith("/epub")) return jsonResponse(current);
    return jsonResponse({}, 404);
  });
}

async function putBody(spy: ReturnType<typeof mockFetch>) {
  let call: Parameters<typeof fetch> | undefined;
  await waitFor(() => {
    call = findCall(spy, (i, init) => methodOf(i, init) === "PUT");
    expect(call).toBeDefined();
  });
  const [input, init] = call as Parameters<typeof fetch>;
  return JSON.parse(await bodyOf(input, init));
}

describe("EpubPacker", () => {
  it("offers packing rules when there are no books and saves the volume split", async () => {
    const spy = mockEpub(overview());
    renderWithProviders(<EpubPacker targetId={1} />);

    await userEvent.click(await screen.findByRole("button", { name: "One book per volume (2)" }));
    // Counts update before saving: chapters 1–2 and 3–4.
    const list = screen.getByRole("list", { name: "EPUB books" });
    expect(within(list).getAllByText("2 ch")).toHaveLength(2);
    expect(screen.getByText("2 books changed")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save books" }));
    expect(await putBody(spy)).toEqual({
      books: [
        { chapter_start: 1, title: null },
        { chapter_start: 3, title: null },
      ],
    });
  });

  it("starts a new book at a chapter picked on the map", async () => {
    const spy = mockEpub(overview({ books: SAVED }));
    renderWithProviders(<EpubPacker targetId={1} />);

    await userEvent.click(await screen.findByRole("button", { name: "Chapter 4, book 2" }));
    expect(screen.getByText(/in book 2 \(c3–c4\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start a new book at c4" }));
    await userEvent.click(screen.getByRole("button", { name: "Save books" }));

    expect(await putBody(spy)).toEqual({
      books: [
        { chapter_start: 1, title: null },
        { chapter_start: 3, title: null },
        { chapter_start: 4, title: null },
      ],
    });
  });

  it("moves the map selection with the arrow keys", async () => {
    mockEpub(overview({ books: SAVED }));
    renderWithProviders(<EpubPacker targetId={1} />);

    const first = await screen.findByRole("button", { name: "Chapter 1, book 1" });
    first.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    const third = screen.getByRole("button", { name: "Chapter 3, book 2" });
    expect(third).toHaveFocus();
    expect(third).toHaveAttribute("aria-pressed", "true");
    // Merging book 2 into book 1 leaves one book.
    await userEvent.click(screen.getByRole("button", { name: "Merge with previous" }));
    expect(screen.getByRole("button", { name: "Chapter 3, book 1" })).toBeInTheDocument();
  });

  it("keeps saved statuses, offers downloads, and exports pending books", async () => {
    const spy = mockEpub(overview({ books: SAVED }));
    renderWithProviders(<EpubPacker targetId={1} />);

    expect(await screen.findByRole("link", { name: "Download book 1" })).toHaveAttribute(
      "href",
      "/api/targets/1/epub/books/11/file",
    );
    await userEvent.click(screen.getByRole("button", { name: "Export 1 pending" }));
    await waitFor(() =>
      expect(findCall(spy, (i) => urlOf(i).endsWith("/api/targets/1/epub/export"))).toBeDefined(),
    );
  });

  it("disables per-book export and discards back to the saved books", async () => {
    mockEpub(overview({ books: SAVED }));
    renderWithProviders(<EpubPacker targetId={1} />);

    await userEvent.type(await screen.findByLabelText("Title of book 2"), "Arc two");
    expect(screen.getByText("1 book changed")).toBeInTheDocument();
    for (const btn of screen.getAllByRole("button", { name: /^(Re-)?export$/i })) {
      expect(btn).toBeDisabled();
    }
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByLabelText("Title of book 2")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Export 1 pending" })).toBeEnabled();
  });

  it("shows a save error from the server", async () => {
    mockFetch(async (input, init) => {
      if (methodOf(input, init) === "PUT") {
        return jsonResponse({ detail: "two books start at chapter 3" }, 400);
      }
      return jsonResponse(overview({ books: SAVED }));
    });
    renderWithProviders(<EpubPacker targetId={1} />);
    await userEvent.type(await screen.findByLabelText("Title of book 1"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save books" }));
    expect(await screen.findByText("two books start at chapter 3")).toBeInTheDocument();
  });

  it("lists chapters without a number as outside every book", async () => {
    const base = overview();
    mockEpub({
      ...base,
      chapters: [
        ...base.chapters,
        {
          number: "Extra",
          title: "",
          volume: "",
          pages: 3,
          file_name: "x.cbz",
          book_position: null,
        },
      ],
    });
    renderWithProviders(<EpubPacker targetId={1} />);
    expect(await screen.findByText(/Not numbered, so in no book: Extra/)).toBeInTheDocument();
  });

  it("explains when the series has not been downloaded", async () => {
    mockEpub(overview({ series: null, chapters: [], suggested_books: [] }));
    renderWithProviders(<EpubPacker targetId={1} />);
    expect(await screen.findByText(/hasn't been downloaded yet/)).toBeInTheDocument();
  });
});

describe("EpubPacker volume fill", () => {
  const MD = "https://mangadex.org/title/0aea9f43-d4a9-4bf7-bebc-550a512f9b95";

  it("hides the action without a MangaDex source", async () => {
    mockEpub(overview());
    renderWithProviders(<EpubPacker targetId={1} />);
    await screen.findByText(/4 chapters/);
    expect(screen.queryByRole("button", { name: "Fill volumes from MangaDex" })).toBeNull();
  });

  it("fills missing volumes and redraws from the returned overview", async () => {
    const filled = overview({
      chapters: overview().chapters.map((c) => ({ ...c, volume: c.number === "4" ? "" : "1" })),
      suggested_books: [
        { title: null, chapter_start: 1 },
        { title: null, chapter_start: 4 },
      ],
    });
    const spy = mockFetch(async (input, init) => {
      const url = urlOf(input);
      if (url.endsWith("/epub/volumes/fill") && methodOf(input, init) === "POST") {
        return jsonResponse({
          source_url: MD,
          chapters: 4,
          missing: 2,
          filled: 1,
          unassigned: 1,
          failed: 0,
          errors: [],
          overview: filled,
        });
      }
      if (url.endsWith("/epub")) return jsonResponse(overview());
      return jsonResponse({}, 404);
    });
    renderWithProviders(<EpubPacker targetId={1} volumeSource={MD} />);

    expect(await screen.findByText(/2 without one/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Fill volumes from MangaDex" }));

    expect(findCall(spy, (i) => urlOf(i).endsWith("/epub/volumes/fill"))).toBeDefined();
    expect(await screen.findByText(/1 without one/)).toBeInTheDocument();
  });
});
