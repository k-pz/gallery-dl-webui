"""Check whether the installed checkout is behind upstream.

The webapp can't run `git fetch` itself (the install lives under
`ProtectSystem=strict`), so we sidestep git entirely: read the current
commit straight from `.git/HEAD` / `.git/refs/heads/<branch>`, derive
owner+repo from `.git/config`'s origin URL, then ask GitHub's public API
for the latest commit on the tracked ref.

The "tracked ref" defaults to the branch from `.git/HEAD` (effectively
`main` in production) but can be overridden via app_config to track a
different branch / tag / SHA for previewing an unreleased version. When
tracking the default branch, we also pull the GitHub Releases between the
installed version and the latest tag so the UI can render proper
changelog entries; on a preview ref there are no release tags to pin
against, so the "changelog" is filled with the per-commit list returned
by GitHub's compare API instead.

The result is cached in-process so repeat polling from the Maintenance
tab doesn't burn through the 60 req/hr unauthenticated GitHub rate limit
on shared NAT exits. The cache key is (tracked_ref, force) — switching
preview refs in the UI bypasses a cache that would otherwise mask the
swap for up to a minute.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from backend.config import REPO_ROOT

logger = logging.getLogger(__name__)

# Match both SSH (`git@github.com:owner/repo.git`) and HTTPS
# (`https://github.com/owner/repo[.git]`) forms. Anything else (e.g. a
# private gitea) we surface as `reason="non_github_origin"` rather than
# guessing.
_GITHUB_ORIGIN_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$"
)

# `version = "X.Y.Z"` in `backend/pyproject.toml`. Anchored on a line-start
# so the [tool.hatch] / [project] etc. ordering doesn't matter. cz keeps
# this literal in lockstep with __version__ via .cz.toml's version_files.
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)

# Strip a leading `v` from a tag like `v1.2.3` to compare against the raw
# semver string in pyproject.toml.
_SEMVER_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class ChangelogEntry:
    """One entry in the upgrade changelog.

    For default-branch tracking this is a GitHub Release (tag/title/body).
    For preview-ref tracking it's one commit between the installed SHA
    and the tracked ref's HEAD — `title` is the commit subject and `body`
    is None.
    """

    title: str
    body: str | None
    ref: str
    published_at: str | None
    html_url: str | None


@dataclass(frozen=True)
class UpdateCheckResult:
    """Outcome of one check. Always populated — failures live in `reason`.

    `behind` is None when we couldn't establish a comparison (no git
    metadata, network error, unsupported origin). `latest_sha` and
    friends are likewise None in those cases.
    """

    branch: str | None
    current_sha: str | None
    current_version: str | None
    tracked_ref: str | None
    tracked_ref_is_default: bool
    latest_sha: str | None
    latest_message: str | None
    latest_committed_at: str | None
    latest_version: str | None
    behind: bool | None
    changelog: list[ChangelogEntry] = field(default_factory=list)
    reason: str | None = None


@dataclass(frozen=True)
class _LocalGitState:
    branch: str
    current_sha: str
    current_version: str | None
    owner: str
    repo: str


_cache: dict[tuple[str | None, str], UpdateCheckResult] = {}
_cache_at: dict[tuple[str | None, str], float] = {}


def _read_first_line(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.readline().strip() or None
    except OSError:
        return None


def _parse_origin_url(config_text: str) -> tuple[str, str] | None:
    """Pull (owner, repo) out of the first `[remote "origin"]` block.

    `.git/config` is INI-ish; we don't need a full parser — just locate
    the origin section and grab its `url =` line.
    """
    in_origin = False
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_origin = line == '[remote "origin"]'
            continue
        if not in_origin:
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "url":
            continue
        match = _GITHUB_ORIGIN_RE.match(value.strip())
        if match:
            return match["owner"], match["repo"]
        return None
    return None


def _read_local_version(repo_root: Path) -> str | None:
    """Pull the installed version off `backend/pyproject.toml`.

    Single source of truth per .cz.toml: cz keeps it in lockstep with
    `backend/src/backend/__init__.py::__version__` and
    `frontend/package.json`. Reading the file directly (rather than
    importing `backend`) keeps this checker test-isolated: a tmp_path
    `.git` layout in the unit tests stays free of an installed package
    bleeding the host's version through.
    """
    pyproject = repo_root / "backend" / "pyproject.toml"
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _VERSION_RE.search(content)
    return match.group(1) if match else None


def read_local_state(repo_root: Path) -> tuple[_LocalGitState | None, str | None]:
    """Inspect `.git/` for the branch + commit + origin. Reason on failure.

    The path-unit-installed CT layout keeps `.git/` next to `backend/`.
    Returns `(state, None)` on success or `(None, "reason")` if anything
    is missing — useful for showing the user *why* the check is inert.
    """
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        return None, "not_a_git_clone"

    head_raw = _read_first_line(git_dir / "HEAD")
    if head_raw is None:
        return None, "missing_head"

    if head_raw.startswith("ref: "):
        ref = head_raw[len("ref: ") :]
        if not ref.startswith("refs/heads/"):
            return None, "detached_head"
        branch = ref[len("refs/heads/") :]
        sha = _read_first_line(git_dir / ref)
        if sha is None:
            # Branch ref might live in packed-refs (e.g. after a fresh shallow
            # clone). Best-effort scan; bail out cleanly if it's not there.
            sha = _packed_ref_sha(git_dir / "packed-refs", ref)
        if sha is None:
            return None, "missing_branch_ref"
    else:
        # Detached HEAD — current_sha is the HEAD content itself, but we have
        # no branch to compare upstream against. Surface as such.
        return None, "detached_head"

    config_path = git_dir / "config"
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError:
        return None, "missing_config"
    parsed = _parse_origin_url(config_text)
    if parsed is None:
        return None, "non_github_origin"
    owner, repo = parsed
    return (
        _LocalGitState(
            branch=branch,
            current_sha=sha,
            current_version=_read_local_version(repo_root),
            owner=owner,
            repo=repo,
        ),
        None,
    )


def _packed_ref_sha(packed_refs: Path, ref: str) -> str | None:
    try:
        with packed_refs.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith(("#", "^")):
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        return None
    return None


def _parse_semver(version: str | None) -> tuple[int, int, int] | None:
    """Return (major, minor, patch) for a `vX.Y.Z` / `X.Y.Z` string, else None.

    Pre-release / build-metadata suffixes are not handled — the release
    workflow doesn't produce them, and a non-matching tag (e.g. `nightly`)
    just drops out of the changelog window rather than crashing.
    """
    if not version:
        return None
    match = _SEMVER_TAG_RE.match(version.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


async def _fetch_commit(
    client: httpx.AsyncClient, owner: str, repo: str, ref: str
) -> tuple[dict | None, str | None]:
    """One unauthenticated GET to GitHub's commits endpoint.

    Errors collapse into a single `reason` so the UI can show "couldn't
    reach upstream" without unspooling stack traces. 404 is its own bucket
    because it usually means the branch was renamed or removed upstream.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}"
    try:
        resp = await client.get(url, headers={"Accept": "application/vnd.github+json"})
    except httpx.TimeoutException, httpx.TransportError:
        return None, "network_error"
    if resp.status_code == 404:
        return None, "branch_not_on_remote"
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        return None, "rate_limited"
    if resp.status_code >= 400:
        logger.warning("update-check: GitHub returned %s for %s", resp.status_code, url)
        return None, "upstream_error"
    try:
        return resp.json(), None
    except ValueError:
        return None, "upstream_error"


async def _fetch_releases(
    client: httpx.AsyncClient, owner: str, repo: str, *, per_page: int = 30
) -> list[dict] | None:
    """List recent releases, newest first. Best-effort: None on failure.

    Used to render the changelog between the installed and latest
    version when tracking the default branch. Drafts are excluded by
    default at the GitHub API level; prereleases come back inline and
    the caller filters them.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    try:
        resp = await client.get(
            url,
            headers={"Accept": "application/vnd.github+json"},
            params={"per_page": str(per_page)},
        )
    except httpx.TimeoutException, httpx.TransportError:
        return None
    if resp.status_code >= 400:
        logger.warning("update-check: GitHub releases returned %s for %s", resp.status_code, url)
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    return payload if isinstance(payload, list) else None


async def _fetch_compare(
    client: httpx.AsyncClient, owner: str, repo: str, base: str, head: str
) -> list[dict] | None:
    """List commits between `base` and `head` (head wins on a fork point).

    The compare endpoint returns up to 250 commits in a single page; we
    cap at that and let the UI truncate further. None on any failure —
    the preview-mode changelog just stays empty in that case.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base}...{head}"
    try:
        resp = await client.get(url, headers={"Accept": "application/vnd.github+json"})
    except httpx.TimeoutException, httpx.TransportError:
        return None
    if resp.status_code >= 400:
        logger.warning("update-check: GitHub compare returned %s for %s", resp.status_code, url)
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    commits = payload.get("commits") if isinstance(payload, dict) else None
    return commits if isinstance(commits, list) else None


def _build_release_changelog(
    releases: list[dict], current_version: str | None
) -> tuple[list[ChangelogEntry], str | None]:
    """Slice the release list to entries newer than `current_version`.

    Returns `(entries, latest_version)`. `latest_version` is the
    highest semver-parseable tag in the list — what the UI shows as
    "Available". Entries are sorted descending (newest first) the way
    GitHub returns them. Non-semver tags (`nightly`, hand-cut releases)
    skip the filter and stay out of the comparison.
    """
    current_tuple = _parse_semver(current_version) if current_version else None
    entries: list[ChangelogEntry] = []
    latest_version: str | None = None
    latest_tuple: tuple[int, int, int] | None = None
    for r in releases:
        if not isinstance(r, dict):
            continue
        tag = r.get("tag_name")
        if not isinstance(tag, str):
            continue
        rel_tuple = _parse_semver(tag)
        if rel_tuple is None:
            continue
        # Track the highest semver tag we've seen — that's the headline
        # "Available" version regardless of whether the installed version
        # parses.
        if latest_tuple is None or rel_tuple > latest_tuple:
            latest_tuple = rel_tuple
            latest_version = tag
        # Only include releases strictly newer than installed. If the
        # installed version doesn't parse (e.g. dev build), surface every
        # release as a candidate upgrade so the user can still see what's
        # there.
        if current_tuple is not None and rel_tuple <= current_tuple:
            continue
        name_raw = r.get("name")
        body_raw = r.get("body")
        published_raw = r.get("published_at")
        url_raw = r.get("html_url")
        entries.append(
            ChangelogEntry(
                title=name_raw if isinstance(name_raw, str) and name_raw else tag,
                body=body_raw if isinstance(body_raw, str) and body_raw else None,
                ref=tag,
                published_at=published_raw if isinstance(published_raw, str) else None,
                html_url=url_raw if isinstance(url_raw, str) else None,
            )
        )
    return entries, latest_version


def _build_compare_changelog(commits: list[dict]) -> list[ChangelogEntry]:
    """Turn the compare-API commit list into changelog entries.

    Order matches GitHub: oldest -> newest. We flip to newest-first so
    the UI matches the release-mode list (most recent at the top).
    """
    entries: list[ChangelogEntry] = []
    for c in commits:
        if not isinstance(c, dict):
            continue
        sha = c.get("sha")
        if not isinstance(sha, str):
            continue
        commit = c.get("commit") or {}
        message_raw = commit.get("message") if isinstance(commit, dict) else None
        subject = (
            message_raw.splitlines()[0]
            if isinstance(message_raw, str) and message_raw
            else "(no subject)"
        )
        committer = commit.get("committer") if isinstance(commit, dict) else None
        date = committer.get("date") if isinstance(committer, dict) else None
        url = c.get("html_url")
        entries.append(
            ChangelogEntry(
                title=subject,
                body=None,
                ref=sha,
                published_at=date if isinstance(date, str) else None,
                html_url=url if isinstance(url, str) else None,
            )
        )
    entries.reverse()
    return entries


async def check_for_updates(
    *,
    repo_root: Path | None = None,
    timeout: float = 5.0,
    force: bool = False,
    ref_override: str | None = None,
) -> UpdateCheckResult:
    """Compare the local checkout's commit to upstream on GitHub.

    `ref_override` selects a non-default ref to track (e.g. `develop`,
    `feature/foo`, a tag, or a SHA). When None, we track the branch from
    `.git/HEAD` (production: `main`). `force=True` skips the in-memory
    TTL cache — used by manual "refresh" actions in the UI.
    """
    global _cache, _cache_at
    now = time.monotonic()
    state, reason = read_local_state(repo_root if repo_root is not None else REPO_ROOT)
    # The cache key includes the tracked ref so flipping preview refs
    # in the UI doesn't get masked by a 60 s stale entry from the
    # previous ref. When we can't read local state we still cache the
    # (None, "") slot so an inert repo doesn't hammer the filesystem.
    cache_key = (ref_override, state.branch if state is not None else "")
    if not force:
        cached = _cache.get(cache_key)
        cached_at = _cache_at.get(cache_key)
        if cached is not None and cached_at is not None and now - cached_at < _CACHE_TTL_SECONDS:
            return cached

    if state is None:
        result = UpdateCheckResult(
            branch=None,
            current_sha=None,
            current_version=None,
            tracked_ref=ref_override,
            tracked_ref_is_default=ref_override is None,
            latest_sha=None,
            latest_message=None,
            latest_committed_at=None,
            latest_version=None,
            behind=None,
            changelog=[],
            reason=reason,
        )
        _cache[cache_key] = result
        _cache_at[cache_key] = now
        return result

    tracked_ref = ref_override if ref_override else state.branch
    tracked_is_default = ref_override is None or ref_override == state.branch

    async with httpx.AsyncClient(timeout=timeout) as client:
        head_payload, fetch_reason = await _fetch_commit(
            client, state.owner, state.repo, tracked_ref
        )
        if head_payload is None:
            result = UpdateCheckResult(
                branch=state.branch,
                current_sha=state.current_sha,
                current_version=state.current_version,
                tracked_ref=tracked_ref,
                tracked_ref_is_default=tracked_is_default,
                latest_sha=None,
                latest_message=None,
                latest_committed_at=None,
                latest_version=None,
                behind=None,
                changelog=[],
                reason=fetch_reason,
            )
            _cache[cache_key] = result
            _cache_at[cache_key] = now
            return result

        latest_sha_raw = head_payload.get("sha")
        latest_sha = latest_sha_raw if isinstance(latest_sha_raw, str) else None
        commit = head_payload.get("commit") or {}
        full_message = commit.get("message") if isinstance(commit, dict) else None
        latest_message = (
            full_message.splitlines()[0] if isinstance(full_message, str) and full_message else None
        )
        committer = commit.get("committer") if isinstance(commit, dict) else None
        latest_committed_at_raw = committer.get("date") if isinstance(committer, dict) else None
        latest_committed_at = (
            latest_committed_at_raw if isinstance(latest_committed_at_raw, str) else None
        )

        behind = latest_sha is not None and latest_sha != state.current_sha

        # Default-branch tracking: pull GitHub Releases between the
        # installed version and the latest tag. Preview-ref tracking: list
        # the commits between current_sha and the ref's HEAD via /compare.
        changelog: list[ChangelogEntry] = []
        latest_version: str | None = None
        if behind:
            if tracked_is_default:
                releases = await _fetch_releases(client, state.owner, state.repo)
                if releases is not None:
                    changelog, latest_version = _build_release_changelog(
                        releases, state.current_version
                    )
            else:
                commits = await _fetch_compare(
                    client, state.owner, state.repo, state.current_sha, tracked_ref
                )
                if commits is not None:
                    changelog = _build_compare_changelog(commits)

    result = UpdateCheckResult(
        branch=state.branch,
        current_sha=state.current_sha,
        current_version=state.current_version,
        tracked_ref=tracked_ref,
        tracked_ref_is_default=tracked_is_default,
        latest_sha=latest_sha,
        latest_message=latest_message,
        latest_committed_at=latest_committed_at,
        latest_version=latest_version,
        behind=behind,
        changelog=changelog,
        reason=None,
    )
    _cache[cache_key] = result
    _cache_at[cache_key] = now
    return result


def _reset_cache_for_tests() -> None:
    """Tests rely on a fresh probe per assertion; the TTL would otherwise mask
    the second call. Production code never touches this.
    """
    global _cache, _cache_at
    _cache = {}
    _cache_at = {}
