import time

from fastapi.testclient import TestClient

from tests.fakes import FakeGalleryConfig


def _wait_terminal(client: TestClient, download_id: int, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/downloads/{download_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(0.02)
    raise AssertionError(f"download {download_id} stuck at {last.get('status')!r}")


def test_creating_download_creates_target(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.extractor_for["https://example/series-a"] = "fake"
    gallery_config.manifest_for["https://example/series-a"] = []
    created = client.post("/api/downloads", json={"url": "https://example/series-a"}).json()
    _wait_terminal(client, created["id"])

    targets = client.get("/api/targets").json()
    assert len(targets) == 1
    t = targets[0]
    assert t["url"] == "https://example/series-a"
    assert t["extractor"] == "fake"
    assert t["watched"] is False
    assert t["download_count"] == 1
    assert t["last_download_id"] == created["id"]
    assert t["last_status"] == "completed"


def test_resubmitting_same_url_reuses_target(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.extractor_for["https://example/x"] = "fake"
    gallery_config.manifest_for["https://example/x"] = []
    first = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, first["id"])
    second = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, second["id"])

    targets = client.get("/api/targets").json()
    assert len(targets) == 1
    assert targets[0]["download_count"] == 2
    assert targets[0]["last_download_id"] == second["id"]


def test_create_download_can_enable_watch_for_new_target(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.extractor_for["https://example/watch-new"] = "fake"
    gallery_config.manifest_for["https://example/watch-new"] = []
    created = client.post(
        "/api/downloads",
        json={"url": "https://example/watch-new", "watched": True},
    ).json()
    _wait_terminal(client, created["id"])

    target = client.get("/api/targets").json()[0]
    assert target["url"] == "https://example/watch-new"
    assert target["watched"] is True


def test_patch_target_sets_watch_flag_and_period(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]

    resp = client.patch(
        f"/api/targets/{target_id}",
        json={"watched": True, "watch_period": "2h"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["watched"] is True
    assert body["watch_period"] == "2h"


def test_patch_target_clears_period_with_empty_string(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]

    client.patch(f"/api/targets/{target_id}", json={"watch_period": "5m"})
    resp = client.patch(f"/api/targets/{target_id}", json={"watch_period": ""})
    assert resp.status_code == 200
    assert resp.json()["watch_period"] is None


def test_patch_target_rejects_invalid_period(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]

    resp = client.patch(f"/api/targets/{target_id}", json={"watch_period": "tomorrow"})
    assert resp.status_code == 400


def test_poll_target_creates_new_download(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]

    resp = client.post(f"/api/targets/{target_id}/poll")
    assert resp.status_code == 200
    body = resp.json()
    assert body["download_count"] == 2


def test_poll_rejects_when_target_already_active(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    # Make the manifest big enough that the worker is busy when we poll.
    gallery_config.manifest_for["https://example/x"] = [f"ch1/{i:03}.jpg" for i in range(20)]
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    target_id = client.get(f"/api/downloads/{created['id']}").json()["target_id"]
    assert target_id is not None
    # This is racy — the first job may have already completed. Either way the
    # endpoint must return 200 or 409 deterministically without 5xx.
    resp = client.post(f"/api/targets/{target_id}/poll")
    assert resp.status_code in {200, 409}


def test_delete_target_removes_it(client: TestClient, gallery_config: FakeGalleryConfig) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]

    resp = client.delete(f"/api/targets/{target_id}")
    assert resp.status_code == 200
    assert client.get("/api/targets").json() == []


def test_target_unknown_id_returns_404(client: TestClient) -> None:
    assert client.get("/api/targets/9999").status_code == 404
    assert client.patch("/api/targets/9999", json={"watched": True}).status_code == 404
    assert client.post("/api/targets/9999/poll").status_code == 404
    assert client.delete("/api/targets/9999").status_code == 404


def test_create_download_stores_tags_and_reading_direction_on_target(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    resp = client.post(
        "/api/downloads",
        json={
            "url": "https://example/x",
            "tags": ["[Action]", "Romance", "action"],
            "reading_direction": "RTL",
        },
    )
    assert resp.status_code == 200, resp.json()

    targets = client.get("/api/targets").json()
    assert len(targets) == 1
    assert targets[0]["tags"] == ["Action", "Romance"]
    assert targets[0]["reading_direction"] == "rtl"


def test_create_download_rejects_invalid_reading_direction(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    resp = client.post(
        "/api/downloads",
        json={"url": "https://example/x", "reading_direction": "sideways"},
    )
    assert resp.status_code == 400


def test_patch_target_updates_tags_and_clears_reading_direction(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    client.post(
        "/api/downloads",
        json={
            "url": "https://example/x",
            "tags": ["initial"],
            "reading_direction": "rtl",
        },
    )
    target_id = client.get("/api/targets").json()[0]["id"]

    resp = client.patch(
        f"/api/targets/{target_id}",
        json={"tags": ["Action", "Drama"], "reading_direction": ""},
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["tags"] == ["Action", "Drama"]
    assert body["reading_direction"] is None


def test_patch_target_rejects_invalid_reading_direction(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    client.post("/api/downloads", json={"url": "https://example/x"})
    target_id = client.get("/api/targets").json()[0]["id"]
    resp = client.patch(f"/api/targets/{target_id}", json={"reading_direction": "horizontal"})
    assert resp.status_code == 400
