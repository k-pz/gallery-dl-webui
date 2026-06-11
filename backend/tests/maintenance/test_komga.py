"""Unit tests for the Komga push helper.

These exercise `push_series_statuses` directly with an injected
`httpx.MockTransport` — no FastAPI client, no DB. Integration is covered
separately in `test_router.py`.
"""

from __future__ import annotations

import httpx
import pytest

from backend.maintenance.komga import (
    KomgaCredentials,
    SeriesForMetadataSync,
    TargetForPush,
    load_credentials,
    metadata_patch_payload,
    push_series_statuses,
    sync_series_metadata,
)


def _make_factory(handler):
    """Build a `client_factory` that returns an `AsyncClient` backed by `handler`."""
    transport = httpx.MockTransport(handler)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://komga.example",
            headers={"X-API-Key": "secret"},
            transport=transport,
            timeout=5.0,
        )

    return factory


@pytest.fixture
def creds() -> KomgaCredentials:
    return KomgaCredentials(base_url="http://komga.example", api_key="secret")


def test_load_credentials_strips_trailing_slash() -> None:
    out = load_credentials({"komga_base_url": "http://k/", "komga_api_key": "secret"})
    assert out.base_url == "http://k"
    assert out.api_key == "secret"


def test_load_credentials_strips_surrounding_whitespace() -> None:
    out = load_credentials({"komga_base_url": "  http://k  ", "komga_api_key": "  secret  "})
    assert out.base_url == "http://k"
    assert out.api_key == "secret"


def test_load_credentials_rejects_missing_url() -> None:
    with pytest.raises(ValueError, match="not configured"):
        load_credentials({"komga_base_url": "", "komga_api_key": "secret"})


def test_load_credentials_rejects_missing_key() -> None:
    with pytest.raises(ValueError, match="not configured"):
        load_credentials({"komga_base_url": "http://k", "komga_api_key": ""})


def test_load_credentials_rejects_missing_both() -> None:
    with pytest.raises(ValueError, match="not configured"):
        load_credentials({})


def test_load_credentials_rejects_bare_host() -> None:
    with pytest.raises(ValueError, match="http://"):
        load_credentials({"komga_base_url": "komga.example", "komga_api_key": "k"})


async def test_push_updates_single_matching_series(creds: KomgaCredentials) -> None:
    patched: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            assert request.url.params.get("search") == "Berserk"
            return httpx.Response(
                200,
                json={"content": [{"id": "abc123", "name": "Berserk"}]},
            )
        if request.method == "PATCH" and request.url.path == "/api/v1/series/abc123/metadata":
            import json

            patched.append((request.url.path, json.loads(request.content)))
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Berserk", series_status="Hiatus")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1
    assert result.total == 1
    assert result.unmatched == []
    assert result.ambiguous == []
    # `statusLock: True` pins the field so Komga's next library scan can't
    # silently revert our REST value via the Mylar series.json importer.
    assert patched == [
        ("/api/v1/series/abc123/metadata", {"status": "HIATUS", "statusLock": True}),
    ]


async def test_push_maps_all_known_statuses(creds: KomgaCredentials) -> None:
    sent_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            name = request.url.params["search"]
            return httpx.Response(200, json={"content": [{"id": f"id-{name}", "name": name}]})
        import json

        sent_payloads.append(json.loads(request.content))
        return httpx.Response(204)

    targets = [
        TargetForPush(name="A", series_status="Ongoing"),
        TargetForPush(name="B", series_status="Ended"),
        TargetForPush(name="C", series_status="Hiatus"),
        TargetForPush(name="D", series_status="Abandoned"),
    ]
    result = await push_series_statuses(creds, targets, client_factory=_make_factory(handler))
    assert result.updated == 4
    assert [p["status"] for p in sent_payloads] == ["ONGOING", "ENDED", "HIATUS", "ABANDONED"]
    assert all(p["statusLock"] is True for p in sent_payloads)


async def test_push_skips_zero_matches(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": []})

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Unknown", series_status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 0
    assert result.skipped_no_match == 1
    assert result.unmatched == ["Unknown"]
    assert result.as_dict()["unmatched"] == ["Unknown"]


async def test_push_skips_multiple_matches(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {"id": "1", "name": "Ambiguous"},
                    {"id": "2", "name": "Ambiguous"},
                ]
            },
        )

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Ambiguous", series_status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 0
    assert result.skipped_multi_match == 1
    assert result.ambiguous == ["Ambiguous"]
    assert result.as_dict()["ambiguous"] == ["Ambiguous"]


async def test_push_filters_substring_matches_from_komga_search(creds: KomgaCredentials) -> None:
    """Komga's `search` does a fuzzy/substring match, so we filter client-side."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"id": "1", "name": "One Piece"},
                        {"id": "2", "name": "One Piece Party"},
                    ]
                },
            )
        return httpx.Response(204)

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="One Piece", series_status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1


async def test_push_matches_against_sanitized_directory_name(creds: KomgaCredentials) -> None:
    """A target name with filename-illegal chars matches Komga's sanitized series name.

    Komga shows the on-disk directory name (post-`sanitize`) when series.json
    hasn't been imported yet, so the match must succeed even though Komga's
    `name` differs from the raw target name (`:` → `_`, `?` stripped, etc.).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"content": [{"id": "abc", "name": "Re_Zero kara Hajimeru"}]},
            )
        return httpx.Response(204)

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Re:Zero kara Hajimeru", series_status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1


async def test_push_matches_with_unicode_casefold(creds: KomgaCredentials) -> None:
    """Match should use Unicode case folding (e.g. ß ↔ SS) rather than ASCII .lower()."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"content": [{"id": "x", "name": "Straße"}]})
        return httpx.Response(204)

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="STRASSE", series_status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1


async def test_push_skips_target_with_no_local_status(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call Komga for status-less target")

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Series", series_status="")],
        client_factory=_make_factory(handler),
    )
    assert result.skipped_no_status == 1
    assert result.updated == 0


async def test_push_skips_unknown_local_status(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call Komga with unmapped status")

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Series", series_status="Mystery")],
        client_factory=_make_factory(handler),
    )
    assert result.skipped_unknown_status == 1


async def test_push_counts_failed_search(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(500, json={"error": "boom"})
        raise AssertionError("PATCH should not be reached after failed search")

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Series", series_status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.failed == 1
    assert result.updated == 0


async def test_push_counts_failed_patch(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"content": [{"id": "x", "name": "Series"}]})
        return httpx.Response(400, json={"error": "bad enum"})

    result = await push_series_statuses(
        creds,
        [TargetForPush(name="Series", series_status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.failed == 1
    assert result.updated == 0


async def test_push_records_progress_lines(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"content": [{"id": "x", "name": "Series"}]})
        return httpx.Response(204)

    seen_total: list[int] = []
    seen_lines: list[str] = []

    await push_series_statuses(
        creds,
        [TargetForPush(name="Series", series_status="Ongoing")],
        on_total=seen_total.append,
        on_step=seen_lines.append,
        client_factory=_make_factory(handler),
    )
    assert seen_total == [1]
    assert any("updated" in line for line in seen_lines)


async def test_push_invokes_on_cancel_with_partial_result(creds: KomgaCredentials) -> None:
    """Cancellation between iterations should hand the partial result to the caller."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            name = request.url.params["search"]
            return httpx.Response(200, json={"content": [{"id": "x", "name": name}]})
        calls["n"] += 1
        return httpx.Response(204)

    seen_partial: list[dict] = []

    async def on_cancel(partial) -> None:
        seen_partial.append(partial.as_dict())

    # Cancel after the first update.
    flag = {"cancel": False}

    def should_cancel() -> bool:
        return flag["cancel"]

    targets = [
        TargetForPush(name="A", series_status="Ongoing"),
        TargetForPush(name="B", series_status="Ongoing"),
    ]

    def on_step(line: str) -> None:
        if "updated: A" in line:
            flag["cancel"] = True

    result = await push_series_statuses(
        creds,
        targets,
        on_step=on_step,
        should_cancel=should_cancel,
        on_cancel=on_cancel,
        client_factory=_make_factory(handler),
    )
    # Only one PATCH happened before cancel, and on_cancel was invoked with
    # the partial result.
    assert result.updated == 1
    assert seen_partial and seen_partial[0]["updated"] == 1


# ---------------------------------------------------------------------------
# sync_series_metadata
# ---------------------------------------------------------------------------


def test_metadata_patch_payload_includes_only_known_fields_with_locks() -> None:
    payload = metadata_patch_payload(
        SeriesForMetadataSync(
            name="Berserk",
            status="Ongoing",
            summary="Dark fantasy.",
            publisher="Hakusensha",
            language="en",
            reading_direction="rtl",
            tags=("Action", "Seinen"),
        )
    )
    assert payload == {
        "status": "ONGOING",
        "statusLock": True,
        "summary": "Dark fantasy.",
        "summaryLock": True,
        "publisher": "Hakusensha",
        "publisherLock": True,
        "language": "en",
        "languageLock": True,
        "readingDirection": "RIGHT_TO_LEFT",
        "readingDirectionLock": True,
        "tags": ["Action", "Seinen"],
        "tagsLock": True,
    }


def test_metadata_patch_payload_drops_unknown_status_and_direction() -> None:
    payload = metadata_patch_payload(
        SeriesForMetadataSync(name="X", status="Mystery", reading_direction="diagonal")
    )
    assert payload == {}


@pytest.mark.parametrize(
    ("local", "komga"),
    [
        ("ltr", "LEFT_TO_RIGHT"),
        ("rtl", "RIGHT_TO_LEFT"),
        ("vertical", "VERTICAL"),
        ("webtoon", "WEBTOON"),
    ],
)
def test_metadata_patch_payload_maps_all_reading_directions(local: str, komga: str) -> None:
    payload = metadata_patch_payload(SeriesForMetadataSync(name="X", reading_direction=local))
    assert payload["readingDirection"] == komga
    assert payload["readingDirectionLock"] is True


async def test_sync_patches_full_metadata(creds: KomgaCredentials) -> None:
    patched: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            return httpx.Response(200, json={"content": [{"id": "abc123", "name": "Berserk"}]})
        if request.method == "PATCH" and request.url.path == "/api/v1/series/abc123/metadata":
            import json

            patched.append((request.url.path, json.loads(request.content)))
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    result = await sync_series_metadata(
        creds,
        [
            SeriesForMetadataSync(
                name="Berserk",
                status="Hiatus",
                summary="Dark fantasy.",
                language="en",
                reading_direction="rtl",
                tags=("Seinen",),
            )
        ],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1
    assert result.total == 1
    assert len(patched) == 1
    body = patched[0][1]
    assert body["status"] == "HIATUS"
    assert body["summary"] == "Dark fantasy."
    assert body["language"] == "en"
    assert body["readingDirection"] == "RIGHT_TO_LEFT"
    assert body["tags"] == ["Seinen"]
    # Every pushed field is locked so Komga's scan-time importers can't
    # overwrite it.
    assert all(body[k] is True for k in body if k.endswith("Lock"))


async def test_sync_skips_series_with_nothing_to_push(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call Komga for a field-less series")

    result = await sync_series_metadata(
        creds,
        [SeriesForMetadataSync(name="Empty")],
        client_factory=_make_factory(handler),
    )
    assert result.skipped_no_fields == 1
    assert result.updated == 0


async def test_sync_pushes_partial_fields_when_status_unknown(creds: KomgaCredentials) -> None:
    """An unmappable status doesn't block the rest of the metadata."""
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"content": [{"id": "x", "name": "Series"}]})
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(204)

    result = await sync_series_metadata(
        creds,
        [SeriesForMetadataSync(name="Series", status="Mystery", summary="Plot.")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1
    assert sent == [{"summary": "Plot.", "summaryLock": True}]


async def test_sync_records_unmatched_and_ambiguous(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params["search"]
        if name == "Ghost":
            return httpx.Response(200, json={"content": []})
        return httpx.Response(
            200,
            json={"content": [{"id": "1", "name": name}, {"id": "2", "name": name}]},
        )

    result = await sync_series_metadata(
        creds,
        [
            SeriesForMetadataSync(name="Ghost", status="Ongoing"),
            SeriesForMetadataSync(name="Twins", status="Ongoing"),
        ],
        client_factory=_make_factory(handler),
    )
    assert result.skipped_no_match == 1
    assert result.unmatched == ["Ghost"]
    assert result.skipped_multi_match == 1
    assert result.ambiguous == ["Twins"]
    assert result.as_dict()["unmatched"] == ["Ghost"]


async def test_sync_counts_failed_patch(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"content": [{"id": "x", "name": "Series"}]})
        return httpx.Response(400, json={"error": "bad"})

    result = await sync_series_metadata(
        creds,
        [SeriesForMetadataSync(name="Series", status="Ongoing")],
        client_factory=_make_factory(handler),
    )
    assert result.failed == 1
    assert result.updated == 0


async def test_sync_invokes_on_cancel_with_partial_result(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            name = request.url.params["search"]
            return httpx.Response(200, json={"content": [{"id": "x", "name": name}]})
        return httpx.Response(204)

    seen_partial: list[dict] = []

    async def on_cancel(partial) -> None:
        seen_partial.append(partial.as_dict())

    flag = {"cancel": False}

    def on_step(line: str) -> None:
        if line.startswith("updated: A"):
            flag["cancel"] = True

    result = await sync_series_metadata(
        creds,
        [
            SeriesForMetadataSync(name="A", status="Ongoing"),
            SeriesForMetadataSync(name="B", status="Ongoing"),
        ],
        on_step=on_step,
        should_cancel=lambda: flag["cancel"],
        on_cancel=on_cancel,
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1
    assert seen_partial and seen_partial[0]["updated"] == 1


async def test_sync_sends_book_authors_for_matched_series(creds: KomgaCredentials) -> None:
    """A series with writer/penciller fans the cleaned names out per book."""
    import json

    book_patches: list[tuple[str, dict]] = []
    series_patches: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            return httpx.Response(200, json={"content": [{"id": "s1", "name": "Berserk"}]})
        if request.method == "GET" and request.url.path == "/api/v1/series/s1/books":
            return httpx.Response(
                200,
                json={"content": [{"id": "b1"}, {"id": "b2"}], "last": True},
            )
        if request.method == "PATCH" and request.url.path == "/api/v1/series/s1/metadata":
            series_patches.append(json.loads(request.content))
            return httpx.Response(204)
        if request.method == "PATCH" and request.url.path.startswith("/api/v1/books/"):
            book_patches.append((request.url.path, json.loads(request.content)))
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    result = await sync_series_metadata(
        creds,
        [
            SeriesForMetadataSync(
                name="Berserk",
                status="Ended",
                writer="Author One, Author Two",
                penciller="Artist",
            )
        ],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1
    assert result.books_updated == 2
    assert result.books_failed == 0
    assert series_patches == [{"status": "ENDED", "statusLock": True}]
    expected_authors = [
        {"name": "Author One", "role": "writer"},
        {"name": "Author Two", "role": "writer"},
        {"name": "Artist", "role": "penciller"},
    ]
    # `authorsLock: True` pins the clean values so a scan of a not-yet
    # regenerated archive can't re-import the stray-quote names over them.
    assert book_patches == [
        ("/api/v1/books/b1/metadata", {"authors": expected_authors, "authorsLock": True}),
        ("/api/v1/books/b2/metadata", {"authors": expected_authors, "authorsLock": True}),
    ]


async def test_sync_sends_authors_even_without_series_fields(creds: KomgaCredentials) -> None:
    """The series-PATCH and author legs are independent — authors alone still sync."""
    book_patches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            return httpx.Response(200, json={"content": [{"id": "s1", "name": "Berserk"}]})
        if request.method == "GET" and request.url.path == "/api/v1/series/s1/books":
            return httpx.Response(200, json={"content": [{"id": "b1"}], "last": True})
        if request.method == "PATCH" and request.url.path.startswith("/api/v1/books/"):
            book_patches.append(request.url.path)
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    result = await sync_series_metadata(
        creds,
        [SeriesForMetadataSync(name="Berserk", writer="Author")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 0
    assert result.skipped_no_fields == 0
    assert result.books_updated == 1
    assert book_patches == ["/api/v1/books/b1/metadata"]


async def test_sync_counts_failed_book_patches(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            return httpx.Response(200, json={"content": [{"id": "s1", "name": "S"}]})
        if request.method == "GET" and request.url.path == "/api/v1/series/s1/books":
            return httpx.Response(200, json={"content": [{"id": "b1"}, {"id": "b2"}]})
        if request.url.path == "/api/v1/books/b1/metadata":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(204)

    result = await sync_series_metadata(
        creds,
        [SeriesForMetadataSync(name="S", status="Ongoing", writer="A")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1
    assert result.books_updated == 1
    assert result.books_failed == 1
    assert result.as_dict()["books_failed"] == 1


async def test_sync_counts_failed_book_listing(creds: KomgaCredentials) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            return httpx.Response(200, json={"content": [{"id": "s1", "name": "S"}]})
        if request.method == "GET" and request.url.path == "/api/v1/series/s1/books":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(204)

    result = await sync_series_metadata(
        creds,
        [SeriesForMetadataSync(name="S", status="Ongoing", writer="A")],
        client_factory=_make_factory(handler),
    )
    assert result.updated == 1
    assert result.failed == 1
    assert result.books_updated == 0


async def test_sync_pages_through_book_listing(creds: KomgaCredentials) -> None:
    """Book listings larger than one page are walked via Komga's `last` flag."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            return httpx.Response(200, json={"content": [{"id": "s1", "name": "S"}]})
        if request.method == "GET" and request.url.path == "/api/v1/series/s1/books":
            page = int(request.url.params.get("page", "0"))
            if page == 0:
                return httpx.Response(200, json={"content": [{"id": "b1"}], "last": False})
            return httpx.Response(200, json={"content": [{"id": "b2"}], "last": True})
        return httpx.Response(204)

    result = await sync_series_metadata(
        creds,
        [SeriesForMetadataSync(name="S", status="Ongoing", writer="A")],
        client_factory=_make_factory(handler),
    )
    assert result.books_updated == 2
