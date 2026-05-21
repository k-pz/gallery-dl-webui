from pathlib import Path

import yaml
from fastapi.testclient import TestClient


def _create_target(client: TestClient, url: str) -> int:
    resp = client.post("/api/downloads", json={"url": url})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["target_id"]


def test_export_library_returns_yaml(client: TestClient) -> None:
    _create_target(client, "https://example/a")
    _create_target(client, "https://example/b")

    resp = client.get("/api/library/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/yaml")
    parsed = yaml.safe_load(resp.text)
    assert parsed["version"] == 1
    urls = {entry["url"] for entry in parsed["series"]}
    assert urls == {"https://example/a", "https://example/b"}
    # Every entry round-trips a watch block (even when defaults are on).
    for entry in parsed["series"]:
        assert entry["watch"] == {"enabled": False}


def test_export_library_includes_watch_state_and_name(client: TestClient) -> None:
    target_id = _create_target(client, "https://example/x")
    # Capture a name as the worker would after metadata extraction.
    resp = client.patch(
        f"/api/targets/{target_id}",
        json={"watched": True, "watch_period": "2h"},
    )
    assert resp.status_code == 200

    parsed = yaml.safe_load(client.get("/api/library/export").text)
    entry = next(e for e in parsed["series"] if e["url"] == "https://example/x")
    assert entry["watch"] == {"enabled": True, "period": "2h"}


def test_import_library_creates_new_targets(client: TestClient) -> None:
    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [
                {
                    "url": "https://example/fresh",
                    "name": "Fresh Series",
                    "watch": {"enabled": True, "period": "1d"},
                }
            ],
        },
        sort_keys=False,
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result == {"imported": 1, "updated": 0, "errors": []}

    listed = client.get("/api/targets").json()
    fresh = next(t for t in listed if t["url"] == "https://example/fresh")
    assert fresh["name"] == "Fresh Series"
    assert fresh["watched"] is True
    assert fresh["watch_period"] == "1d"


def test_import_library_updates_existing_target(client: TestClient) -> None:
    _create_target(client, "https://example/x")
    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [
                {
                    "url": "https://example/x",
                    "watch": {"enabled": True, "period": "6h"},
                }
            ],
        },
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"imported": 0, "updated": 1, "errors": []}

    target = next(t for t in client.get("/api/targets").json() if t["url"] == "https://example/x")
    assert target["watched"] is True
    assert target["watch_period"] == "6h"


def test_import_library_rejects_unsupported_version(client: TestClient) -> None:
    body = yaml.safe_dump({"version": 999, "series": []})
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 400


def test_import_library_collects_per_entry_errors(client: TestClient) -> None:
    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [
                {"url": "https://ok/one"},
                {"url": "https://bad/two", "watch": {"enabled": True, "period": "not-a-period"}},
                {"name": "missing url"},
            ],
        }
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["imported"] == 1
    assert result["updated"] == 0
    assert len(result["errors"]) == 2


def test_library_roundtrips_tags_and_reading_direction(client: TestClient) -> None:
    client.post(
        "/api/downloads",
        json={
            "url": "https://example/series",
            "tags": ["Action", "Drama"],
            "reading_direction": "rtl",
        },
    )
    exported = yaml.safe_load(client.get("/api/library/export").text)
    entry = next(e for e in exported["series"] if e["url"] == "https://example/series")
    assert entry["tags"] == ["Action", "Drama"]
    assert entry["reading_direction"] == "rtl"

    # Re-import the same payload onto a fresh target and confirm fields land.
    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [
                {
                    "url": "https://example/other",
                    "tags": ["[Drama]", "drama"],
                    "reading_direction": "vertical",
                }
            ],
        }
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    other = next(
        t for t in client.get("/api/targets").json() if t["url"] == "https://example/other"
    )
    assert other["tags"] == ["Drama"]
    assert other["reading_direction"] == "vertical"


def test_library_roundtrips_series_status(client: TestClient) -> None:
    client.post("/api/downloads", json={"url": "https://example/status-series"})
    target_id = client.get("/api/targets").json()[0]["id"]
    client.patch(f"/api/targets/{target_id}", json={"series_status": "Hiatus"})

    exported = yaml.safe_load(client.get("/api/library/export").text)
    entry = next(e for e in exported["series"] if e["url"] == "https://example/status-series")
    assert entry["series_status"] == "Hiatus"

    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [{"url": "https://example/fresh", "series_status": "Ended"}],
        }
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    fresh = next(
        t for t in client.get("/api/targets").json() if t["url"] == "https://example/fresh"
    )
    assert fresh["series_status"] == "Ended"


def test_library_import_rejects_invalid_series_status(client: TestClient) -> None:
    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [{"url": "https://example/bad", "series_status": "Publishing"}],
        }
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["imported"] == 0
    assert any("series_status" in err for err in result["errors"])


def test_import_library_validates_output_dir_under_root(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
        },
    )
    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [
                {
                    "url": "https://ok/series",
                    "output_dir": str(root / "manga"),
                },
                {
                    "url": "https://bad/series",
                    "output_dir": "/etc/nope",
                },
            ],
        }
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["imported"] == 1
    assert len(result["errors"]) == 1
    assert "must be under root" in result["errors"][0] or "must be" in result["errors"][0]
