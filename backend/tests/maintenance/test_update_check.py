"""Unit tests for backend.maintenance.update_check.

The check has three moving parts: parsing `.git/` on disk, hitting the
GitHub API over httpx, and an in-process TTL cache. We exercise each
layer in isolation so a failure in any one of them produces a single
clear test.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from backend.maintenance import update_check


def _make_repo(
    root: Path, *, head_sha: str, branch: str = "main", origin: str | None = None
) -> None:
    """Lay out a minimal .git/ that read_local_state can consume."""
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "refs" / "heads" / branch).write_text(f"{head_sha}\n", encoding="utf-8")
    config = "[core]\n\trepositoryformatversion = 0\n"
    if origin is not None:
        config += f'[remote "origin"]\n\turl = {origin}\n'
    (git / "config").write_text(config, encoding="utf-8")


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


async def test_check_for_updates_reports_behind(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/o/r/commits/main"
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

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.behind is True
    assert result.current_sha == "old"
    assert result.latest_sha == "new"
    assert result.latest_message == "feat: shiny"
    assert result.latest_committed_at == "2026-05-22T10:00:00Z"
    assert result.reason is None


async def test_check_for_updates_reports_up_to_date(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path, head_sha="same", origin="https://github.com/o/r.git")

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sha": "same", "commit": {"message": "x"}})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    result = await update_check.check_for_updates(repo_root=tmp_path)
    assert result.behind is False
    assert result.latest_sha == "same"
    assert result.reason is None


async def test_check_for_updates_collapses_network_errors(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git")

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

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


async def test_check_for_updates_caches_repeated_calls(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path, head_sha="old", origin="https://github.com/o/r.git")
    calls = {"count": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"sha": "new", "commit": {"message": "x"}})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    first = await update_check.check_for_updates(repo_root=tmp_path)
    second = await update_check.check_for_updates(repo_root=tmp_path)
    assert calls["count"] == 1
    assert first == second

    # force=True bypasses the cache.
    await update_check.check_for_updates(repo_root=tmp_path, force=True)
    assert calls["count"] == 2
