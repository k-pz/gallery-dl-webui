"""Unit tests for backend.maintenance.update_check.

The check has four moving parts: parsing `.git/` on disk, reading the
installed version off pyproject.toml, hitting the GitHub API over httpx
(commits / releases / compare), and an in-process TTL cache. We exercise
each layer in isolation so a failure in any one of them produces a
single clear test.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from backend.maintenance import update_check


def _make_repo(
    root: Path,
    *,
    head_sha: str,
    branch: str = "main",
    origin: str | None = None,
    version: str | None = None,
) -> None:
    """Lay out a minimal .git/ that read_local_state can consume.

    `version` writes a matching `backend/pyproject.toml` so the version
    reader has something to find — None skips it (mimics a repo without
    cz on it).
    """
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "refs" / "heads" / branch).write_text(f"{head_sha}\n", encoding="utf-8")
    config = "[core]\n\trepositoryformatversion = 0\n"
    if origin is not None:
        config += f'[remote "origin"]\n\turl = {origin}\n'
    (git / "config").write_text(config, encoding="utf-8")
    if version is not None:
        backend_dir = root / "backend"
        backend_dir.mkdir(exist_ok=True)
        (backend_dir / "pyproject.toml").write_text(
            f'[project]\nname = "backend"\nversion = "{version}"\n', encoding="utf-8"
        )


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler: object) -> None:
    """Wire a MockTransport into every AsyncClient instantiation."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Each test starts from a clean cache so the 60 s TTL doesn't leak."""
    update_check._reset_cache_for_tests()


def test_read_local_state_happy_path(tmp_path: Path) -> None:
    _make_repo(tmp_path, head_sha="abc123", origin="https://github.com/k-pz/gallery-dl-webui.git")
    state, reason = update_check.read_local_state(tmp_path)
    assert reason is None
    assert state is not None
    assert state.branch == "main"
    assert state.current_sha == "abc123"
    assert (state.owner, state.repo) == ("k-pz", "gallery-dl-webui")


def test_read_local_state_handles_ssh_origin(tmp_path: Path) -> None:
    _make_repo(tmp_path, head_sha="abc123", origin="git@github.com:owner/proj.git")
    state, reason = update_check.read_local_state(tmp_path)
    assert reason is None
    assert state is not None
    assert (state.owner, state.repo) == ("owner", "proj")


def test_read_local_state_handles_origin_without_dot_git(tmp_path: Path) -> None:
    _make_repo(tmp_path, head_sha="abc", origin="https://github.com/owner/proj")
    state, _ = update_check.read_local_state(tmp_path)
    assert state is not None
    assert (state.owner, state.repo) == ("owner", "proj")


def test_read_local_state_flags_non_github_origin(tmp_path: Path) -> None:
    _make_repo(tmp_path, head_sha="abc", origin="https://gitlab.com/owner/proj.git")
    state, reason = update_check.read_local_state(tmp_path)
    assert state is None
    assert reason == "non_github_origin"


def test_read_local_state_flags_missing_git(tmp_path: Path) -> None:
    state, reason = update_check.read_local_state(tmp_path)
    assert state is None
    assert reason == "not_a_git_clone"


def test_read_local_state_flags_detached_head(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("0123456789abcdef\n", encoding="utf-8")
    state, reason = update_check.read_local_state(tmp_path)
    assert state is None
    assert reason == "detached_head"


def test_read_local_state_resolves_packed_refs(tmp_path: Path) -> None:
    """Shallow clones leave the branch ref in packed-refs, not on disk."""
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/o/r.git\n', encoding="utf-8"
    )
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "deadbeef refs/heads/main\n"
        "feedface refs/tags/v1\n",
        encoding="utf-8",
    )
    state, reason = update_check.read_local_state(tmp_path)
    assert reason is None
    assert state is not None
    assert state.current_sha == "deadbeef"


def test_read_local_state_reads_pyproject_version(tmp_path: Path) -> None:
    _make_repo(tmp_path, head_sha="abc", origin="https://github.com/o/r.git", version="1.2.3")
    state, _ = update_check.read_local_state(tmp_path)
    assert state is not None
    assert state.current_version == "1.2.3"


def test_read_local_state_handles_missing_pyproject(tmp_path: Path) -> None:
    _make_repo(tmp_path, head_sha="abc", origin="https://github.com/o/r.git")
    state, _ = update_check.read_local_state(tmp_path)
    assert state is not None
    assert state.current_version is None


async def test_check_for_updates_reports_behind_with_changelog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git", version="1.0.0")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/o/r/commits/main":
            return httpx.Response(
                200,
                json={
                    "sha": "new",
                    "commit": {
                        "message": "feat: shiny\n\nbody text",
                        "committer": {"date": "2026-05-22T10:00:00Z"},
                    },
                },
            )
        if path == "/repos/o/r/releases":
            return httpx.Response(
                200,
                json=[
                    {
                        "tag_name": "v1.1.0",
                        "name": "v1.1.0 — Shiny",
                        "body": "## Features\n- feat: shiny",
                        "published_at": "2026-05-22T10:00:00Z",
                        "html_url": "https://github.com/o/r/releases/tag/v1.1.0",
                    },
                    {
                        "tag_name": "v1.0.0",
                        "name": "v1.0.0",
                        "body": "Initial",
                        "published_at": "2026-05-01T10:00:00Z",
                        "html_url": "https://github.com/o/r/releases/tag/v1.0.0",
                    },
                ],
            )
        if path == "/repos/o/r/tags":
            return httpx.Response(
                200,
                json=[
                    {"name": "v1.1.0"},
                    {"name": "v1.0.0"},
                    {"name": "nightly"},
                ],
            )
        raise AssertionError(f"unexpected GitHub call to {path}")

    _patch_httpx(monkeypatch, handler)

    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.behind is True
    assert result.current_sha == "old"
    assert result.current_version == "1.0.0"
    assert result.latest_sha == "new"
    assert result.latest_version == "v1.1.0"
    assert result.tracked_ref == "main"
    assert result.tracked_ref_is_default is True
    assert result.latest_message == "feat: shiny"
    assert result.latest_committed_at == "2026-05-22T10:00:00Z"
    assert result.reason is None
    assert [e.ref for e in result.changelog] == ["v1.1.0"]
    assert result.changelog[0].title == "v1.1.0 — Shiny"
    # Tag picker stays populated independent of the changelog window.
    # Non-semver names (`nightly`) are dropped.
    assert result.available_tags == ["v1.1.0", "v1.0.0"]


async def test_check_for_updates_reports_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_repo(tmp_path, head_sha="same", origin="https://github.com/o/r.git", version="1.0.0")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/commits/main":
            return httpx.Response(200, json={"sha": "same", "commit": {"message": "x"}})
        if request.url.path == "/repos/o/r/tags":
            return httpx.Response(200, json=[{"name": "v1.0.0"}])
        raise AssertionError(f"unexpected call to {request.url.path} (releases should be skipped)")

    _patch_httpx(monkeypatch, handler)

    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.behind is False
    assert result.latest_sha == "same"
    assert result.changelog == []
    assert result.reason is None
    # Tags are fetched even when up-to-date, so the picker stays usable.
    assert result.available_tags == ["v1.0.0"]


async def test_check_for_updates_collapses_network_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git")

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _patch_httpx(monkeypatch, handler)

    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.behind is None
    assert result.reason == "network_error"
    # Local state still surfaces — the UI can still show the installed SHA.
    assert result.current_sha == "old"


async def test_check_for_updates_skips_when_no_git_dir(tmp_path: Path) -> None:
    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.reason == "not_a_git_clone"
    assert result.behind is None
    assert result.current_sha is None


async def test_check_for_updates_caches_repeated_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if request.url.path == "/repos/o/r/commits/main":
            return httpx.Response(200, json={"sha": "new", "commit": {"message": "x"}})
        if request.url.path == "/repos/o/r/releases":
            return httpx.Response(200, json=[])
        if request.url.path == "/repos/o/r/tags":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected call to {request.url.path}")

    _patch_httpx(monkeypatch, handler)

    first = await update_check.check_for_updates(repo_root=tmp_path)
    second = await update_check.check_for_updates(repo_root=tmp_path)
    assert first == second
    cached_calls = calls["count"]

    # force=True bypasses the cache and re-issues both upstream calls.
    await update_check.check_for_updates(repo_root=tmp_path, force=True)
    assert calls["count"] > cached_calls


async def test_check_for_updates_ref_override_uses_compare_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preview ref → commits queried from the override, changelog from /compare."""
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git", version="1.0.0")

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path == "/repos/o/r/commits/develop":
            return httpx.Response(
                200,
                json={
                    "sha": "tip",
                    "commit": {
                        "message": "feat(preview): things",
                        "committer": {"date": "2026-05-22T10:00:00Z"},
                    },
                },
            )
        if path == "/repos/o/r/compare/old...develop":
            return httpx.Response(
                200,
                json={
                    "commits": [
                        {
                            "sha": "mid",
                            "commit": {
                                "message": "feat(preview): mid commit",
                                "committer": {"date": "2026-05-21T10:00:00Z"},
                            },
                            "html_url": "https://github.com/o/r/commit/mid",
                        },
                        {
                            "sha": "tip",
                            "commit": {
                                "message": "feat(preview): things",
                                "committer": {"date": "2026-05-22T10:00:00Z"},
                            },
                            "html_url": "https://github.com/o/r/commit/tip",
                        },
                    ]
                },
            )
        if path == "/repos/o/r/releases":
            raise AssertionError("releases endpoint should not be called on a preview ref")
        if path == "/repos/o/r/tags":
            return httpx.Response(200, json=[{"name": "v1.1.0"}])
        raise AssertionError(f"unexpected GitHub call to {path}")

    _patch_httpx(monkeypatch, handler)

    result = await update_check.check_for_updates(repo_root=tmp_path, ref_override="develop")
    assert result.behind is True
    assert result.tracked_ref == "develop"
    assert result.tracked_ref_is_default is False
    # changelog comes back newest-first
    assert [e.ref for e in result.changelog] == ["tip", "mid"]
    assert result.changelog[0].title == "feat(preview): things"
    assert "/repos/o/r/commits/develop" in seen
    assert "/repos/o/r/compare/old...develop" in seen


async def test_check_for_updates_ref_override_matching_branch_stays_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting ref_override to the same branch the .git/HEAD already tracks is a no-op."""
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git", version="1.0.0")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/commits/main":
            return httpx.Response(200, json={"sha": "new", "commit": {"message": "x"}})
        if request.url.path == "/repos/o/r/releases":
            return httpx.Response(200, json=[])
        if request.url.path == "/repos/o/r/tags":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected GitHub call to {request.url.path}")

    _patch_httpx(monkeypatch, handler)

    result = await update_check.check_for_updates(repo_root=tmp_path, ref_override="main")
    assert result.tracked_ref == "main"
    assert result.tracked_ref_is_default is True


def test_build_release_changelog_filters_to_newer_releases() -> None:
    entries, latest = update_check._build_release_changelog(
        [
            {
                "tag_name": "v1.2.0",
                "name": "v1.2.0",
                "body": "two",
                "published_at": None,
                "html_url": "https://example/2",
            },
            {
                "tag_name": "v1.1.0",
                "name": "v1.1.0",
                "body": "one",
                "published_at": None,
                "html_url": "https://example/1",
            },
            {
                "tag_name": "v1.0.0",
                "name": "v1.0.0",
                "body": "zero",
                "published_at": None,
                "html_url": "https://example/0",
            },
            # Non-semver tags are skipped entirely and never become "latest".
            {"tag_name": "nightly", "body": "rolling"},
        ],
        current_version="1.0.0",
    )
    assert latest == "v1.2.0"
    assert [e.ref for e in entries] == ["v1.2.0", "v1.1.0"]


async def test_check_for_updates_tags_sorted_and_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub returns tags in any order; the result is descending semver."""
    _make_repo(tmp_path, head_sha="same", origin="https://github.com/o/r.git", version="1.0.0")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/commits/main":
            return httpx.Response(200, json={"sha": "same", "commit": {"message": "x"}})
        if request.url.path == "/repos/o/r/tags":
            return httpx.Response(
                200,
                json=[
                    {"name": "v1.0.0"},
                    {"name": "v2.0.0"},
                    {"name": "v1.5.1"},
                    {"name": "nightly"},
                    {"name": "v1.5.0-rc1"},  # non-canonical → dropped
                ],
            )
        raise AssertionError(f"unexpected call to {request.url.path}")

    _patch_httpx(monkeypatch, handler)

    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.available_tags == ["v2.0.0", "v1.5.1", "v1.0.0"]


async def test_check_for_updates_tags_empty_on_fetch_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 5xx on /tags collapses to an empty list — the picker just gets smaller."""
    _make_repo(tmp_path, head_sha="same", origin="https://github.com/o/r.git", version="1.0.0")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/commits/main":
            return httpx.Response(200, json={"sha": "same", "commit": {"message": "x"}})
        if request.url.path == "/repos/o/r/tags":
            return httpx.Response(500, text="boom")
        raise AssertionError(f"unexpected call to {request.url.path}")

    _patch_httpx(monkeypatch, handler)

    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.available_tags == []
    # The check itself still succeeded — reason stays None.
    assert result.reason is None


def test_build_release_changelog_passes_all_when_current_unknown() -> None:
    """A dev install with no parseable version still gets every release listed."""
    entries, latest = update_check._build_release_changelog(
        [
            {"tag_name": "v1.1.0", "body": "one", "name": None},
            {"tag_name": "v1.0.0", "body": "zero", "name": None},
        ],
        current_version=None,
    )
    assert latest == "v1.1.0"
    assert {e.ref for e in entries} == {"v1.1.0", "v1.0.0"}
