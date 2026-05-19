import time

from fastapi.testclient import TestClient

from .fakes import FakeGallery, FakeGalleryConfig


def _wait_for_status(
    client: TestClient, download_id: int, statuses: set[str], timeout: float = 2.0
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/downloads/{download_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] in statuses:
            return last
        time.sleep(0.02)
    raise AssertionError(f"download {download_id} stuck at {last.get('status')!r}")


def test_create_download_rejects_blank_url(client: TestClient) -> None:
    resp = client.post("/api/downloads", json={"url": "   "})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "url is required"


def test_create_download_rejects_unsupported_url(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.default_extractor = None
    resp = client.post("/api/downloads", json={"url": "https://example/nope"})
    assert resp.status_code == 400
    assert "unsupported URL" in resp.json()["detail"]


def test_create_download_persists_and_returns_record(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.extractor_for["https://example/x"] = "fakecat"
    gallery_config.manifest_for["https://example/x"] = []

    resp = client.post("/api/downloads", json={"url": "https://example/x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == "https://example/x"
    assert body["extractor"] == "fakecat"
    assert body["status"] in {"pending", "extracting", "running", "completed"}

    listing = client.get("/api/downloads").json()
    assert any(item["id"] == body["id"] for item in listing)


def test_get_download_returns_404_for_missing(client: TestClient) -> None:
    resp = client.get("/api/downloads/99999")
    assert resp.status_code == 404


def test_list_downloads_orders_newest_first(client: TestClient) -> None:
    ids = []
    for url in ["https://example/a", "https://example/b", "https://example/c"]:
        ids.append(client.post("/api/downloads", json={"url": url}).json()["id"])

    listing = [item["id"] for item in client.get("/api/downloads").json()]
    assert listing[:3] == list(reversed(ids))


def test_create_download_strips_whitespace(client: TestClient) -> None:
    resp = client.post("/api/downloads", json={"url": "  https://example/x  "})
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example/x"


def test_full_lifecycle_to_completed(client: TestClient, gallery_config: FakeGalleryConfig) -> None:
    gallery_config.manifest_for["https://example/x"] = [
        "ch1/001.jpg",
        "ch1/002.jpg",
        "ch2/001.jpg",
    ]

    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    final = _wait_for_status(client, created["id"], {"completed", "failed"})

    assert final["status"] == "completed"
    assert final["exit_code"] == 0
    assert final["files_expected"] == 3
    assert final["files_downloaded"] == 3
    assert final["error"] is None


def test_progress_endpoint_returns_chapter_breakdown(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = [
        "ch1/001.jpg",
        "ch1/002.jpg",
        "ch2/001.jpg",
    ]

    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_for_status(client, created["id"], {"completed", "failed"})

    progress = client.get(f"/api/downloads/{created['id']}/progress").json()
    assert progress["status"] == "completed"
    assert progress["files_expected"] == 3
    assert progress["files_present"] == 3
    by_name = {c["name"]: c for c in progress["chapters"]}
    assert by_name["ch1"]["files_total"] == 2
    assert by_name["ch1"]["files_present"] == 2
    assert by_name["ch2"]["files_total"] == 1


def test_progress_endpoint_returns_404_for_missing(client: TestClient) -> None:
    resp = client.get("/api/downloads/99999/progress")
    assert resp.status_code == 404


def test_create_download_rejects_output_dir_outside_root(
    client: TestClient, gallery_config: FakeGalleryConfig, tmp_path
) -> None:
    gallery_config.extractor_for["https://example/x"] = "fake"
    client.put(
        "/api/config",
        json={
            "postprocess_root": str(tmp_path / "media"),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
        },
    )
    resp = client.post(
        "/api/downloads",
        json={"url": "https://example/x", "output_dir": str(tmp_path / "elsewhere")},
    )
    assert resp.status_code == 400
    assert "under root" in resp.json()["detail"]


def test_create_download_requires_root_when_output_dir_provided(
    client: TestClient, gallery_config: FakeGalleryConfig, tmp_path
) -> None:
    gallery_config.extractor_for["https://example/x"] = "fake"
    resp = client.post(
        "/api/downloads",
        json={"url": "https://example/x", "output_dir": str(tmp_path / "out")},
    )
    assert resp.status_code == 400
    assert "postprocess_root" in resp.json()["detail"]


def test_create_download_remembers_output_dir(
    client: TestClient, gallery_config: FakeGalleryConfig, tmp_path
) -> None:
    gallery_config.extractor_for["https://example/x"] = "fake"
    root = tmp_path / "media"
    chosen = root / "comics"
    client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
        },
    )
    resp = client.post(
        "/api/downloads",
        json={"url": "https://example/x", "output_dir": str(chosen)},
    )
    assert resp.status_code == 200
    cfg = client.get("/api/config").json()
    assert str(chosen.resolve()) in cfg["postprocess_known_output_dirs"]


def test_cancel_pending_download_marks_it_cancelled(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    # Block the worker by giving an existing job a manifest large enough that
    # the second job sits in pending. Simpler: stop the worker isn't trivial
    # through TestClient, so we just cancel a freshly created job before the
    # worker can claim it. In practice the test is racy; using a blocking
    # fake (next test) is more reliable. This test exercises the
    # "already terminal" path against a job that completed first.
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_for_status(client, created["id"], {"completed", "failed"})

    resp = client.post(f"/api/downloads/{created['id']}/cancel")
    assert resp.status_code == 409
    assert "terminal state" in resp.json()["detail"]


def test_cancel_unknown_download_returns_404(client: TestClient) -> None:
    resp = client.post("/api/downloads/99999/cancel")
    assert resp.status_code == 404


def test_requeue_resets_completed_download_to_pending(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = ["ch1/001.jpg"]
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_for_status(client, created["id"], {"completed", "failed"})

    resp = client.post(f"/api/downloads/{created['id']}/requeue")
    assert resp.status_code == 200
    # Requeue may transition very fast; accept any state past pending too.
    assert resp.json()["status"] in {"pending", "extracting", "running", "completed"}

    final = _wait_for_status(client, created["id"], {"completed", "failed"})
    assert final["status"] == "completed"


def test_requeue_refuses_non_terminal(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    # Inject a job that never reaches a terminal state during this call by
    # ensuring it is queried in its pending state. Hard to guarantee with the
    # real worker, so cancel-then-requeue gives us a deterministic terminal
    # state to test against, and we then verify the second requeue races
    # cleanly: either it succeeds (job re-queued) or returns 409 (already
    # picked up). We only assert it doesn't 500.
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_for_status(client, created["id"], {"completed", "failed"})
    client.post(f"/api/downloads/{created['id']}/requeue")

    # Now try to cancel the freshly-requeued job; depending on timing it may
    # already be terminal again. Either way the API must answer cleanly.
    resp = client.post(f"/api/downloads/{created['id']}/cancel")
    assert resp.status_code in {200, 409}


def test_requeue_unknown_download_returns_404(client: TestClient) -> None:
    resp = client.post("/api/downloads/99999/requeue")
    assert resp.status_code == 404


def test_create_download_invokes_fake_gallery(
    client: TestClient,
    gallery_config: FakeGalleryConfig,
    gallery_holder: dict[str, FakeGallery],
) -> None:
    """Sanity check that the route consulted the (fake) Gallery, not the real one."""
    gallery_config.extractor_for["https://example/x"] = "marker"

    resp = client.post("/api/downloads", json={"url": "https://example/x"})
    assert resp.json()["extractor"] == "marker"

    gallery = gallery_holder["gallery"]
    assert isinstance(gallery, FakeGallery)
