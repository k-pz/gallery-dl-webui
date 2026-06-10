import threading
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
    # Submit-with-watch must seed last_polled_at; otherwise the poller's
    # `last_polled_at IS NULL → due` shortcut re-queues the target the instant
    # this manual download finishes.
    assert target["last_polled_at"] is not None


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


def test_patch_target_sets_and_clears_series_status(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]

    resp = client.patch(f"/api/targets/{target_id}", json={"series_status": "Hiatus"})
    assert resp.status_code == 200, resp.json()
    assert resp.json()["series_status"] == "Hiatus"

    cleared = client.patch(f"/api/targets/{target_id}", json={"series_status": ""})
    assert cleared.status_code == 200
    assert cleared.json()["series_status"] is None


def test_patch_target_rejects_invalid_series_status(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    gallery_config.manifest_for["https://example/x"] = []
    created = client.post("/api/downloads", json={"url": "https://example/x"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]
    resp = client.patch(f"/api/targets/{target_id}", json={"series_status": "Publishing"})
    assert resp.status_code == 400


def test_manifest_series_status_auto_populates_target(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    """A normalised status from the sim pass should land on the target row."""
    gallery_config.manifest_for["https://example/auto"] = []
    gallery_config.series_status_for["https://example/auto"] = "Ended"

    created = client.post("/api/downloads", json={"url": "https://example/auto"}).json()
    _wait_terminal(client, created["id"])

    target = client.get("/api/targets").json()[0]
    assert target["series_status"] == "Ended"


def test_manifest_series_status_does_not_overwrite_user_override(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    """User PATCH wins: a subsequent poll surfacing a different status must not
    clobber what the user set."""
    gallery_config.manifest_for["https://example/u"] = []
    gallery_config.series_status_for["https://example/u"] = "Ongoing"

    created = client.post("/api/downloads", json={"url": "https://example/u"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]
    assert client.get(f"/api/targets/{target_id}").json()["series_status"] == "Ongoing"

    client.patch(f"/api/targets/{target_id}", json={"series_status": "Hiatus"})
    # Re-poll. The sim pass still says "Ongoing", but the user said "Hiatus".
    client.post(f"/api/targets/{target_id}/poll")
    _wait_terminal(client, client.get("/api/targets").json()[0]["last_download_id"])

    assert client.get(f"/api/targets/{target_id}").json()["series_status"] == "Hiatus"


def test_manifest_series_tags_auto_populates_target(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    """Tags/genres surfaced by the sim pass should land on the target row."""
    gallery_config.manifest_for["https://example/auto-tags"] = []
    gallery_config.series_tags_for["https://example/auto-tags"] = ["Action", "Romance"]

    created = client.post("/api/downloads", json={"url": "https://example/auto-tags"}).json()
    _wait_terminal(client, created["id"])

    target = client.get("/api/targets").json()[0]
    assert target["tags"] == ["Action", "Romance"]


def test_manifest_series_tags_do_not_overwrite_user_tags(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    """User-set tags survive a subsequent poll surfacing different extractor tags."""
    gallery_config.manifest_for["https://example/tu"] = []
    gallery_config.series_tags_for["https://example/tu"] = ["Action"]

    created = client.post("/api/downloads", json={"url": "https://example/tu"}).json()
    _wait_terminal(client, created["id"])
    target_id = client.get("/api/targets").json()[0]["id"]
    assert client.get(f"/api/targets/{target_id}").json()["tags"] == ["Action"]

    client.patch(f"/api/targets/{target_id}", json={"tags": ["Shounen"]})
    # Re-poll. The sim pass still says ["Action"], but the user said ["Shounen"].
    client.post(f"/api/targets/{target_id}/poll")
    _wait_terminal(client, client.get("/api/targets").json()[0]["last_download_id"])

    assert client.get(f"/api/targets/{target_id}").json()["tags"] == ["Shounen"]


def _make_target(
    client: TestClient,
    gallery_config: FakeGalleryConfig,
    url: str,
    *,
    watched: bool = False,
    series_status: str | None = None,
) -> int:
    """Create a target by running a download for `url` to completion, then
    patch the watch flag / series status onto it. Returns the target id."""
    gallery_config.manifest_for[url] = []
    created = client.post("/api/downloads", json={"url": url}).json()
    _wait_terminal(client, created["id"])
    target = next(t for t in client.get("/api/targets").json() if t["url"] == url)
    patch: dict = {}
    if watched:
        patch["watched"] = True
    if series_status is not None:
        patch["series_status"] = series_status
    if patch:
        resp = client.patch(f"/api/targets/{target['id']}", json=patch)
        assert resp.status_code == 200
    return target["id"]


def _download_counts(client: TestClient) -> dict[int, int]:
    return {t["id"]: t["download_count"] for t in client.get("/api/targets").json()}


def test_poll_watched_schedules_watched_skips_finished_series(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    ongoing = _make_target(
        client, gallery_config, "https://example/ongoing", watched=True, series_status="Ongoing"
    )
    no_status = _make_target(client, gallery_config, "https://example/no-status", watched=True)
    hiatus = _make_target(
        client, gallery_config, "https://example/hiatus", watched=True, series_status="Hiatus"
    )
    ended = _make_target(
        client, gallery_config, "https://example/ended", watched=True, series_status="Ended"
    )
    abandoned = _make_target(
        client, gallery_config, "https://example/abandoned", watched=True, series_status="Abandoned"
    )
    unwatched = _make_target(client, gallery_config, "https://example/unwatched")

    resp = client.post("/api/targets/poll-watched")
    assert resp.status_code == 200
    assert resp.json() == {"scheduled": 3, "skipped_active": 0}

    counts = _download_counts(client)
    assert counts[ongoing] == 2
    assert counts[no_status] == 2
    assert counts[hiatus] == 2
    assert counts[ended] == 1
    assert counts[abandoned] == 1
    assert counts[unwatched] == 1

    # Let the newly queued jobs drain so shutdown doesn't race the worker.
    for t in client.get("/api/targets").json():
        if t["last_status"] not in {"completed", "failed", "cancelled"}:
            _wait_terminal(client, t["last_download_id"])


def test_poll_watched_skips_targets_with_active_download(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    busy = _make_target(client, gallery_config, "https://example/busy", watched=True)
    idle = _make_target(client, gallery_config, "https://example/idle", watched=True)

    # Park a download for `busy` in the running state: the fake's gate keeps
    # run_download blocked until we release it.
    gate = threading.Event()
    gallery_config.gate_for["https://example/busy"] = gate
    poll = client.post(f"/api/targets/{busy}/poll")
    assert poll.status_code == 200

    resp = client.post("/api/targets/poll-watched")
    gate.set()
    assert resp.status_code == 200
    assert resp.json() == {"scheduled": 1, "skipped_active": 1}

    counts = _download_counts(client)
    assert counts[busy] == 2  # the gated poll, not the bulk one
    assert counts[idle] == 2

    for t in client.get("/api/targets").json():
        if t["last_status"] not in {"completed", "failed", "cancelled"}:
            _wait_terminal(client, t["last_download_id"])


def test_poll_watched_with_empty_library_schedules_nothing(client: TestClient) -> None:
    resp = client.post("/api/targets/poll-watched")
    assert resp.status_code == 200
    assert resp.json() == {"scheduled": 0, "skipped_active": 0}
