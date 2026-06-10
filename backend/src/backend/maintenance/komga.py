"""Komga REST API client used by the `push_komga_series_status` maintenance kind.

Kept deliberately narrow: we only need to (a) authenticate against a Komga
instance with an API key, (b) search series by name, and (c) PATCH the series
metadata `status` field. Everything else is out of scope.

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

            try:
                resp = await http.get(
                    "/api/v1/series",
                    params={"search": target.name, "size": 50},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                result.failed += 1
                emit(f"search failed for {target.name!r}: {exc}")
                continue

            try:
                payload = resp.json()
            except ValueError as exc:
                result.failed += 1
                emit(f"search returned non-JSON for {target.name!r}: {exc}")
                continue

            content = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(content, list):
                content = []
            # Match against both the raw target name and the post-`sanitize`
            # directory name: Komga shows the imported series.json `name` when
            # available (raw), but falls back to the on-disk directory name
            # (sanitized) when series.json hasn't been imported yet. `casefold`
            # so non-ASCII titles (ß, Turkish dotless i, etc.) compare under
            # the same Unicode rules Komga uses server-side.
            wanted = {
                target.name.strip().casefold(),
                sanitize(target.name).strip().casefold(),
            }
            exact = [
                s
                for s in content
                if isinstance(s, dict)
                and isinstance(s.get("name"), str)
                and s["name"].strip().casefold() in wanted
            ]

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
