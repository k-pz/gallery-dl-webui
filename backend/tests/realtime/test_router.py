from fastapi.testclient import TestClient

from tests.fakes import FakeGalleryConfig


def test_websocket_streams_downloads_event(
    client: TestClient, gallery_config: FakeGalleryConfig
) -> None:
    """A websocket subscriber should see a `downloads/created` event after a
    POST /api/downloads. The first frame is the `system/connected` handshake.
    """
    gallery_config.extractor_for["https://example/x"] = "fakecat"
    gallery_config.manifest_for["https://example/x"] = []

    with client.websocket_connect("/api/ws") as ws:
        # First frame: handshake.
        handshake = ws.receive_json()
        assert handshake["topic"] == "system"
        assert handshake["type"] == "connected"

        resp = client.post("/api/downloads", json={"url": "https://example/x"})
        assert resp.status_code == 200
        new_id = resp.json()["id"]

        # We accept any downloads event with our id — the worker may emit
        # several before we drain the queue.
        seen_ids: list[int] = []
        for _ in range(10):
            evt = ws.receive_json()
            if evt["topic"] == "downloads":
                seen_ids.append(evt["data"].get("id"))
                if new_id in seen_ids:
                    break
        assert new_id in seen_ids, seen_ids


def test_websocket_streams_config_event(client: TestClient) -> None:
    """`PUT /api/config` publishes a `config/updated` event."""
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "connected"

        resp = client.put(
            "/api/config",
            json={
                "postprocess_root": None,
                "postprocess_default_output_dir": None,
                "delete_raw_after_pack": True,
            },
        )
        assert resp.status_code == 200

        for _ in range(5):
            evt = ws.receive_json()
            if evt["topic"] == "config":
                assert evt["type"] == "updated"
                return
        raise AssertionError("did not receive a config/updated event")
