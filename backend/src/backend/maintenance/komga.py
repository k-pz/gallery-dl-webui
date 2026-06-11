"""Komga REST API client used by the Komga maintenance kinds.

Two jobs run through here: `push_komga_series_status` (status only) and
`sync_komga_metadata` (every series-level field Komga's REST API accepts,
plus author names — Komga has no series-level authors, they aggregate from
book metadata, so the sync fans the cleaned names out per book).
Kept deliberately narrow: we only need to (a) authenticate against a Komga
instance with an API key, (b) search series by name, and (c) PATCH the series
metadata. Everything else is out of scope.

Note on dates: Komga's series-metadata endpoint has no publication-date or
year field — the date Komga shows for a series is aggregated from its books'
release dates, which come from each CBZ's ComicInfo.xml. The first-publication
date we track therefore reaches Komga via series.json + ComicInfo on disk,
not via this client.

Credentials live in `app_config` under `komga_base_url` + `komga_api_key`
(set via the Config tab). The worker loads them at job-start time; a missing
or malformed pair fails the job up front with a user-visible message.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.comic_metadata import sanitize

# Local series_status labels (defined in comic_metadata.SERIES_STATUSES)
# mapped to Komga's REST enum. Komga's series metadata endpoint accepts only
# the four uppercase labels below; anything else is rejected with a 400.
LOCAL_TO_KOMGA_STATUS: dict[str, str] = {
    "Ongoing": "ONGOING",
    "Ended": "ENDED",
    "Hiatus": "HIATUS",
    "Abandoned": "ABANDONED",
}

# Local reading-direction tokens (comic_metadata.READING_DIRECTIONS) mapped to
# Komga's SeriesMetadata.ReadingDirection enum.
KOMGA_READING_DIRECTION_BY_LOCAL: dict[str, str] = {
    "ltr": "LEFT_TO_RIGHT",
    "rtl": "RIGHT_TO_LEFT",
    "vertical": "VERTICAL",
    "webtoon": "WEBTOON",
}


@dataclass(frozen=True)
class KomgaCredentials:
    base_url: str
    api_key: str


@dataclass(frozen=True)
class TargetForPush:
    """A subset of `targets.Target` flattened for the Komga push handler.

    The handler only needs the human-facing name (for search) and the local
    series_status label (for the status enum mapping); decoupling here keeps
    the unit test for the push function free of DB fixtures.
    """

    name: str
    series_status: str


@dataclass
class KomgaPushResult:
    updated: int = 0
    skipped_no_status: int = 0
    skipped_unknown_status: int = 0
    skipped_no_match: int = 0
    skipped_multi_match: int = 0
    failed: int = 0
    total: int = 0
    # Series names behind the two match-failure counters, so the persisted
    # job result can tell the user *which* series to fix, not just how many.
    unmatched: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "updated": self.updated,
            "skipped_no_status": self.skipped_no_status,
            "skipped_unknown_status": self.skipped_unknown_status,
            "skipped_no_match": self.skipped_no_match,
            "skipped_multi_match": self.skipped_multi_match,
            "failed": self.failed,
            "total": self.total,
            "unmatched": list(self.unmatched),
            "ambiguous": list(self.ambiguous),
        }


ProgressLine = Callable[[str], None]
ShouldCancel = Callable[[], bool]


def load_credentials(cfg: dict[str, Any]) -> KomgaCredentials:
    """Pull Komga creds out of the app_config dict, validating shape.

    Raises `ValueError` (caught by the router for a 400, or by the worker to
    mark the job failed) with a user-visible message when either field is
    missing or malformed. Strips trailing slashes from the base URL so
    per-request paths can be joined verbatim.
    """
    base_url_raw = cfg.get("komga_base_url")
    api_key_raw = cfg.get("komga_api_key")
    if not isinstance(base_url_raw, str) or not base_url_raw.strip():
        raise ValueError(
            "Komga is not configured — set komga_base_url + komga_api_key in the Config tab"
        )
    if not isinstance(api_key_raw, str) or not api_key_raw.strip():
        raise ValueError(
            "Komga is not configured — set komga_base_url + komga_api_key in the Config tab"
        )
    base_url = base_url_raw.strip().rstrip("/")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ValueError("komga_base_url must start with http:// or https://")
    return KomgaCredentials(base_url=base_url, api_key=api_key_raw.strip())


_SEARCH_PAGE_SIZE = 50
# Hard ceiling on paging so a pathologically broad search term can't loop
# forever; 10 pages x 50 results is far beyond any realistic name collision.
_SEARCH_MAX_PAGES = 10


async def _find_exact_matches(
    http: httpx.AsyncClient, name: str
) -> tuple[list[dict[str, Any]], str | None]:
    """Search Komga for `name`, paging until the exact matches are collected.

    Matches against both the raw target name and the post-`sanitize`
    directory name: Komga shows the imported series.json `name` when
    available (raw), but falls back to the on-disk directory name (sanitized)
    when series.json hasn't been imported yet. `casefold` so non-ASCII titles
    (ß, Turkish dotless i, etc.) compare under the same Unicode rules Komga
    uses server-side. Returns (matches, None) or ([], error_line).
    """
    wanted = {name.strip().casefold(), sanitize(name).strip().casefold()}
    matches: list[dict[str, Any]] = []
    for page in range(_SEARCH_MAX_PAGES):
        try:
            resp = await http.get(
                "/api/v1/series",
                params={"search": name, "size": _SEARCH_PAGE_SIZE, "page": page},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return [], f"search failed: {exc}"
        try:
            payload = resp.json()
        except ValueError as exc:
            return [], f"search returned non-JSON: {exc}"
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, list):
            content = []
        matches.extend(
            s
            for s in content
            if isinstance(s, dict)
            and isinstance(s.get("name"), str)
            and s["name"].strip().casefold() in wanted
        )
        # Komga's paged responses carry `last`; only an explicit False keeps
        # paging — a missing field (e.g. a single mocked page in tests)
        # stops the loop.
        is_last = payload.get("last") if isinstance(payload, dict) else None
        if is_last is not False:
            break
    return matches, None


async def push_series_statuses(
    creds: KomgaCredentials,
    targets: list[TargetForPush],
    *,
    on_total: Callable[[int], None] | None = None,
    on_step: ProgressLine | None = None,
    should_cancel: ShouldCancel | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    on_cancel: Callable[[KomgaPushResult], Awaitable[None] | None] | None = None,
) -> KomgaPushResult:
    """Push each target's local series_status into the matching Komga series.

    Matching rule: case-insensitive exact match on the series name. Zero or
    multiple matches → log + skip (per the agreed UX), tracked as separate
    counters in the returned result, with the affected series names recorded
    in `unmatched` / `ambiguous` so the persisted result names them.

    `client_factory` exists so tests can inject an `httpx.MockTransport`
    without monkey-patching. `should_cancel` is polled before each per-series
    HTTP round-trip; on a True read the function calls `on_cancel` (so the
    caller can raise `MaintenanceCancelled` with the partial result) and
    returns the partial result.
    """
    result = KomgaPushResult(total=len(targets))
    if on_total is not None:
        on_total(len(targets))

    def emit(line: str) -> None:
        if on_step is not None:
            on_step(line)

    def cancelled() -> bool:
        return bool(should_cancel and should_cancel())

    headers = {"X-API-Key": creds.api_key}

    def _default_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=creds.base_url, headers=headers, timeout=30.0)

    factory = client_factory or _default_factory

    async with factory() as http:
        for target in targets:
            if cancelled():
                if on_cancel is not None:
                    maybe_coro = on_cancel(result)
                    if maybe_coro is not None:
                        await maybe_coro
                return result

            if not target.series_status:
                result.skipped_no_status += 1
                emit(f"skip (no local status): {target.name}")
                continue

            komga_status = LOCAL_TO_KOMGA_STATUS.get(target.series_status)
            if komga_status is None:
                result.skipped_unknown_status += 1
                emit(f"skip (unknown status {target.series_status!r}): {target.name}")
                continue

            exact, search_error = await _find_exact_matches(http, target.name)
            if search_error is not None:
                result.failed += 1
                emit(f"{search_error} for {target.name!r}")
                continue

            if len(exact) == 0:
                result.skipped_no_match += 1
                result.unmatched.append(target.name)
                emit(f"skip (no Komga match): {target.name}")
                continue
            if len(exact) > 1:
                result.skipped_multi_match += 1
                result.ambiguous.append(target.name)
                emit(f"skip ({len(exact)} Komga matches): {target.name}")
                continue

            series_id = exact[0].get("id")
            if not isinstance(series_id, str) or not series_id:
                result.failed += 1
                emit(f"Komga match missing id for {target.name!r}")
                continue

            try:
                # `statusLock: true` pins the field so Komga's next library
                # scan can't overwrite our REST value via the Mylar series.json
                # importer. Without the lock, Hiatus/Abandoned (which we omit
                # from series.json) would survive but Ongoing/Ended would be
                # re-applied on every scan from the wire-format value.
                patch_resp = await http.patch(
                    f"/api/v1/series/{series_id}/metadata",
                    json={"status": komga_status, "statusLock": True},
                )
                patch_resp.raise_for_status()
            except httpx.HTTPError as exc:
                result.failed += 1
                emit(f"update failed for {target.name!r}: {exc}")
                continue

            result.updated += 1
            emit(f"updated: {target.name} → {komga_status}")

    return result


@dataclass(frozen=True)
class SeriesForMetadataSync:
    """Everything `sync_series_metadata` may push for one series.

    Built by the maintenance worker from the target row plus the on-disk
    series.json. Empty/None fields are omitted from the PATCH so a value we
    don't know locally never blanks one Komga already has.
    """

    name: str
    status: str = ""
    summary: str = ""
    publisher: str = ""
    language: str = ""
    reading_direction: str = ""
    tags: tuple[str, ...] = ()
    # Cleaned author names (", "-joined when there are several). These have
    # no series-level Komga field; non-empty values trigger the per-book
    # author PATCH leg of the sync.
    writer: str = ""
    penciller: str = ""


@dataclass
class KomgaSyncResult:
    updated: int = 0
    skipped_no_fields: int = 0
    skipped_no_match: int = 0
    skipped_multi_match: int = 0
    failed: int = 0
    total: int = 0
    # Book-level author push: how many book metadata PATCHes landed/failed
    # across all matched series.
    books_updated: int = 0
    books_failed: int = 0
    unmatched: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "updated": self.updated,
            "skipped_no_fields": self.skipped_no_fields,
            "skipped_no_match": self.skipped_no_match,
            "skipped_multi_match": self.skipped_multi_match,
            "failed": self.failed,
            "total": self.total,
            "books_updated": self.books_updated,
            "books_failed": self.books_failed,
            "unmatched": list(self.unmatched),
            "ambiguous": list(self.ambiguous),
        }


def metadata_patch_payload(series: SeriesForMetadataSync) -> dict[str, Any]:
    """Build the SeriesMetadataUpdate PATCH body for one series.

    Only locally-known (non-empty, mappable) fields are included, and each
    one is locked — Komga locks pin a field against its import providers
    (Mylar series.json, ComicInfo aggregation) re-overwriting it on the next
    library scan, while remaining editable in the Komga UI.
    """
    payload: dict[str, Any] = {}
    status = LOCAL_TO_KOMGA_STATUS.get(series.status)
    if status is not None:
        payload["status"] = status
        payload["statusLock"] = True
    if series.summary:
        payload["summary"] = series.summary
        payload["summaryLock"] = True
    if series.publisher:
        payload["publisher"] = series.publisher
        payload["publisherLock"] = True
    if series.language:
        payload["language"] = series.language
        payload["languageLock"] = True
    direction = KOMGA_READING_DIRECTION_BY_LOCAL.get(series.reading_direction)
    if direction is not None:
        payload["readingDirection"] = direction
        payload["readingDirectionLock"] = True
    if series.tags:
        payload["tags"] = list(series.tags)
        payload["tagsLock"] = True
    return payload


def _author_entries(writer: str, penciller: str) -> list[dict[str, str]] | None:
    """Build the Komga book-metadata `authors` payload from joined name strings.

    Multi-person values arrive ", "-joined (see comic_metadata._author_name);
    split them back into one `{name, role}` entry per person. Returns None
    when both strings are blank so callers can skip the author leg outright.
    """
    entries = [
        {"name": name.strip(), "role": role}
        for role, joined in (("writer", writer), ("penciller", penciller))
        for name in joined.split(",")
        if name.strip()
    ]
    return entries or None


_BOOKS_PAGE_SIZE = 200
# Same defensive ceiling rationale as the series search: 50 pages x 200 books
# covers any realistic series many times over.
_BOOKS_MAX_PAGES = 50


async def _list_book_ids(http: httpx.AsyncClient, series_id: str) -> tuple[list[str], str | None]:
    """Collect every book id of a Komga series, paging until exhausted.

    Returns (ids, None) or ([], error_line), mirroring `_find_exact_matches`.
    """
    ids: list[str] = []
    for page in range(_BOOKS_MAX_PAGES):
        try:
            resp = await http.get(
                f"/api/v1/series/{series_id}/books",
                params={"size": _BOOKS_PAGE_SIZE, "page": page},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return [], f"book listing failed: {exc}"
        try:
            payload = resp.json()
        except ValueError as exc:
            return [], f"book listing returned non-JSON: {exc}"
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, list):
            content = []
        ids.extend(b["id"] for b in content if isinstance(b, dict) and isinstance(b.get("id"), str))
        is_last = payload.get("last") if isinstance(payload, dict) else None
        if is_last is not False:
            break
    return ids, None


async def _push_series_book_authors(
    http: httpx.AsyncClient,
    series_id: str,
    authors: list[dict[str, str]],
    series: SeriesForMetadataSync,
    result: KomgaSyncResult,
    emit: ProgressLine,
) -> None:
    """PATCH the cleaned author entries onto every book of one Komga series.

    `authorsLock: true` pins the values so a library scan of an archive whose
    ComicInfo.xml still carries the stray-quote names (i.e. packed before the
    list-author fix and not yet regenerated) can't re-import the dirty values
    over the clean push. Per-book failures are tallied, not fatal.
    """
    book_ids, listing_error = await _list_book_ids(http, series_id)
    if listing_error is not None:
        result.failed += 1
        emit(f"{listing_error} for {series.name!r}")
        return
    pushed = 0
    for book_id in book_ids:
        try:
            resp = await http.patch(
                f"/api/v1/books/{book_id}/metadata",
                json={"authors": authors, "authorsLock": True},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            result.books_failed += 1
            emit(f"book author update failed for {series.name!r} ({book_id}): {exc}")
            continue
        pushed += 1
    result.books_updated += pushed
    if pushed:
        emit(f"authors → {pushed} book(s): {series.name}")


async def sync_series_metadata(
    creds: KomgaCredentials,
    series_list: list[SeriesForMetadataSync],
    *,
    on_total: Callable[[int], None] | None = None,
    on_step: ProgressLine | None = None,
    should_cancel: ShouldCancel | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    on_cancel: Callable[[KomgaSyncResult], Awaitable[None] | None] | None = None,
) -> KomgaSyncResult:
    """Push each series' locally-known metadata into the matching Komga series.

    Same matching rule and cancellation contract as `push_series_statuses`:
    case-insensitive exact name match, zero/multiple matches → log + skip,
    `should_cancel` polled before each per-series round-trip. A series with
    no pushable fields (no status, nothing on disk) is counted and skipped
    without touching Komga.

    Two legs per matched series: the series-metadata PATCH (status, summary,
    …) and the per-book author PATCH for non-empty writer/penciller. They
    are independent — a series with only authors still syncs them, and a
    failed series PATCH doesn't abort the author leg.
    """
    result = KomgaSyncResult(total=len(series_list))
    if on_total is not None:
        on_total(len(series_list))

    def emit(line: str) -> None:
        if on_step is not None:
            on_step(line)

    def cancelled() -> bool:
        return bool(should_cancel and should_cancel())

    headers = {"X-API-Key": creds.api_key}

    def _default_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=creds.base_url, headers=headers, timeout=30.0)

    factory = client_factory or _default_factory

    async with factory() as http:
        for series in series_list:
            if cancelled():
                if on_cancel is not None:
                    maybe_coro = on_cancel(result)
                    if maybe_coro is not None:
                        await maybe_coro
                return result

            payload = metadata_patch_payload(series)
            authors = _author_entries(series.writer, series.penciller)
            if not payload and authors is None:
                result.skipped_no_fields += 1
                emit(f"skip (no local metadata): {series.name}")
                continue

            exact, search_error = await _find_exact_matches(http, series.name)
            if search_error is not None:
                result.failed += 1
                emit(f"{search_error} for {series.name!r}")
                continue

            if len(exact) == 0:
                result.skipped_no_match += 1
                result.unmatched.append(series.name)
                emit(f"skip (no Komga match): {series.name}")
                continue
            if len(exact) > 1:
                result.skipped_multi_match += 1
                result.ambiguous.append(series.name)
                emit(f"skip ({len(exact)} Komga matches): {series.name}")
                continue

            series_id = exact[0].get("id")
            if not isinstance(series_id, str) or not series_id:
                result.failed += 1
                emit(f"Komga match missing id for {series.name!r}")
                continue

            if payload:
                try:
                    patch_resp = await http.patch(
                        f"/api/v1/series/{series_id}/metadata",
                        json=payload,
                    )
                    patch_resp.raise_for_status()
                except httpx.HTTPError as exc:
                    result.failed += 1
                    emit(f"update failed for {series.name!r}: {exc}")
                else:
                    fields = ", ".join(k for k in payload if not k.endswith("Lock"))
                    result.updated += 1
                    emit(f"updated: {series.name} → {fields}")

            if authors is not None:
                await _push_series_book_authors(http, series_id, authors, series, result, emit)

    return result
