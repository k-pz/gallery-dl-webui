"""Tests for the X-Events response header (request-scoped event forwarding)."""

import json

from fastapi.testclient import TestClient


def test_mutating_request_carries_x_events_header(client: TestClient) -> None:
    resp = client.put(
        "/api/config",
        json={
            "postprocess_root": None,
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "chapter_naming_template": None,
        },
    )
    assert resp.status_code == 200, resp.json()
    raw = resp.headers.get("X-Events")
    assert raw is not None
    events = json.loads(raw)
    assert any(e["topic"] == "config" for e in events)


def test_read_request_has_no_x_events_header(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert "X-Events" not in resp.headers
