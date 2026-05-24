"""Check whether the installed checkout is behind upstream.

The webapp can't run `git fetch` itself (the install lives under
`ProtectSystem=strict`), so we sidestep git entirely: read the current
commit straight from `.git/HEAD` / `.git/refs/heads/<branch>`, derive
owner+repo from `.git/config`'s origin URL, then ask GitHub's public API
for the latest commit on the same branch.

The result is cached in-process so repeat polling from the Maintenance
tab doesn't burn through the 60 req/hr unauthenticated GitHub rate limit
on shared NAT exits.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
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

_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class UpdateCheckResult:
    """Outcome of one check. Always populated — failures live in `reason`.

    `behind` is None when we couldn't establish a comparison (no git
    metadata, network error, unsupported origin). `latest_sha` and
    `latest_message` are likewise None in those cases.
    """

    branch: str | None
    current_sha: str | None
    latest_sha: str | None
    latest_message: str | None
    latest_committed_at: str | None
    behind: bool | None
    reason: str | None


@dataclass(frozen=True)
class _LocalGitState:
    branch: str
    current_sha: str
    owner: str
    repo: str


_cache: tuple[float, UpdateCheckResult] | None = None


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
    return _LocalGitState(branch=branch, current_sha=sha, owner=owner, repo=repo), None


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


async def _fetch_latest_commit(
    owner: str, repo: str, branch: str, *, timeout: float
) -> tuple[dict | None, str | None]:
    """One unauthenticated GET to GitHub's commits endpoint.

    Errors collapse into a single `reason` so the UI can show "couldn't
    reach upstream" without unspooling stack traces. 404 is its own bucket
    because it usually means the branch was renamed or removed upstream.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError):
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


async def check_for_updates(
    *,
    repo_root: Path | None = None,
    timeout: float = 5.0,
    force: bool = False,
) -> UpdateCheckResult:
    """Compare the local checkout's commit to upstream `branch` on GitHub.

    `force=True` skips the in-memory TTL cache — used by manual "refresh"
    actions in the UI. The cache key is implicit (the install only ever
    compares against its own upstream), so a single slot is enough.
    """
    global _cache
    now = time.monotonic()
    if not force and _cache is not None:
        cached_at, cached = _cache
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached

    root = repo_root if repo_root is not None else REPO_ROOT
    state, reason = read_local_state(root)
    if state is None:
        result = UpdateCheckResult(
            branch=None,
            current_sha=None,
            latest_sha=None,
            latest_message=None,
            latest_committed_at=None,
            behind=None,
            reason=reason,
        )
        _cache = (now, result)
        return result

    payload, fetch_reason = await _fetch_latest_commit(
        state.owner, state.repo, state.branch, timeout=timeout
    )
    if payload is None:
        result = UpdateCheckResult(
            branch=state.branch,
            current_sha=state.current_sha,
            latest_sha=None,
            latest_message=None,
            latest_committed_at=None,
            behind=None,
            reason=fetch_reason,
        )
        _cache = (now, result)
        return result

    latest_sha = payload.get("sha")
    commit = payload.get("commit") or {}
    full_message = commit.get("message") or ""
    # Commit messages are multi-line; the first line is the conventional subject.
    latest_message = full_message.splitlines()[0] if full_message else None
    committer = commit.get("committer") or {}
    latest_committed_at = committer.get("date")

    behind = (
        latest_sha is not None and isinstance(latest_sha, str) and latest_sha != state.current_sha
    )
    result = UpdateCheckResult(
        branch=state.branch,
        current_sha=state.current_sha,
        latest_sha=latest_sha if isinstance(latest_sha, str) else None,
        latest_message=latest_message,
        latest_committed_at=latest_committed_at,
        behind=behind,
        reason=None,
    )
    _cache = (now, result)
    return result


def _reset_cache_for_tests() -> None:
    """Tests rely on a fresh probe per assertion; the TTL would otherwise mask
    the second call. Production code never touches this.
    """
    global _cache
    _cache = None
