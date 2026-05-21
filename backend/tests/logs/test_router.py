import json

import pytest
from fastapi.testclient import TestClient

from backend.logs import router as logs_router


def test_normalize_entry_basic_priority_and_timestamp() -> None:
    raw = {
        "PRIORITY": "6",
        "__REALTIME_TIMESTAMP": "1716305000123456",
        "MESSAGE": "hello",
        "_SYSTEMD_UNIT": "gallery-dl-webui.service",
        "SYSLOG_IDENTIFIER": "python",
        "_PID": "1234",
    }
    out = logs_router._normalize_entry(raw)
    assert out["priority"] == 6
    assert out["level"] == "info"
    assert out["ts_ms"] == 1_716_305_000_123
    assert out["message"] == "hello"
    assert out["unit"] == "gallery-dl-webui.service"
    assert out["ident"] == "python"
    assert out["pid"] == "1234"


def test_normalize_entry_priority_falls_back_to_info() -> None:
    out = logs_router._normalize_entry({"MESSAGE": "x"})
    assert out["priority"] == 6
    assert out["level"] == "info"
    assert out["ts_ms"] is None


def test_normalize_entry_debug_level() -> None:
    out = logs_router._normalize_entry({"PRIORITY": 7, "MESSAGE": "noisy"})
    assert out["level"] == "debug"


def test_normalize_entry_binary_message_decodes() -> None:
    # journald renders non-UTF8-safe MESSAGE fields as a list of byte ints.
    out = logs_router._normalize_entry({"PRIORITY": 6, "MESSAGE": [104, 105]})
    assert out["message"] == "hi"


def test_tail_logs_reports_missing_journalctl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logs_router.shutil, "which", lambda _name: None)

    # Avoid spinning up the full app (which opens the DB and workers) — mount
    # the router on a bare FastAPI instance.
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(logs_router.router, prefix="/api")

    with TestClient(app) as client:
        with client.stream("GET", "/api/logs/tail?lines=10") as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes())

    text = body.decode("utf-8")
    assert "event: ready" in text
    assert "event: error" in text
    # Find the error payload and confirm it mentions journalctl.
    error_block = text.split("event: error", 1)[1]
    payload_line = next(
        (line for line in error_block.splitlines() if line.startswith("data: ")),
        None,
    )
    assert payload_line is not None
    payload = json.loads(payload_line[len("data: ") :])
    assert "journalctl" in payload["message"]
