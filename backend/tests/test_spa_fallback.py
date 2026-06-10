"""Tests for the production SPA fallback route.

The regular `client` fixture builds the app with `serve_frontend=False`, so
these tests construct their own app against a fake `frontend/dist` layout.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app

from .fakes import FakeGallery, FakeGalleryConfig


@pytest.fixture
def spa_client(
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (dist / "app.js").write_text("console.log('app')", encoding="utf-8")
    # A file *outside* dist that a traversal would try to reach.
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")

    monkeypatch.setattr("backend.main.FRONTEND_DIST", dist)
    app = create_app(
        settings_factory=lambda: settings,
        gallery_factory=lambda s: FakeGallery(s, config=FakeGalleryConfig()),
        serve_frontend=True,
    )
    with TestClient(app) as c:
        yield c


def test_serves_real_files_from_dist(spa_client: TestClient) -> None:
    resp = spa_client.get("/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('app')"


def test_unknown_route_falls_back_to_index(spa_client: TestClient) -> None:
    resp = spa_client.get("/targets")
    assert resp.status_code == 200
    assert resp.text == "<html>spa</html>"


def test_percent_encoded_traversal_is_contained(spa_client: TestClient) -> None:
    # httpx would normalize a literal `/../`, but the percent-encoded form
    # reaches the route verbatim and Starlette's `:path` converter decodes it.
    resp = spa_client.get("/%2e%2e/secret.txt")
    assert resp.status_code == 200
    assert resp.text == "<html>spa</html>"
    assert "top secret" not in resp.text


def test_nested_traversal_is_contained(spa_client: TestClient) -> None:
    resp = spa_client.get("/assets/%2e%2e/%2e%2e/secret.txt")
    assert "top secret" not in resp.text
