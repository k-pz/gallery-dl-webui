from pathlib import Path

from fastapi.testclient import TestClient


def test_get_config_returns_defaults(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["postprocess_output_dir"] is None
    assert body["delete_raw_after_pack"] is True


def test_put_config_persists_values(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "out"
    resp = client.put(
        "/api/config",
        json={
            "postprocess_output_dir": str(target),
            "delete_raw_after_pack": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["postprocess_output_dir"] == str(target)
    assert body["delete_raw_after_pack"] is False
    # Directory should have been created.
    assert target.is_dir()
    # And the value should survive a follow-up GET.
    follow = client.get("/api/config").json()
    assert follow["postprocess_output_dir"] == str(target)
    assert follow["delete_raw_after_pack"] is False


def test_put_config_rejects_relative_path(client: TestClient) -> None:
    resp = client.put(
        "/api/config",
        json={"postprocess_output_dir": "relative/dir", "delete_raw_after_pack": True},
    )
    assert resp.status_code == 400
    assert "absolute path" in resp.json()["detail"]


def test_put_config_rejects_missing_parent(client: TestClient, tmp_path: Path) -> None:
    # Parent does not exist.
    missing = tmp_path / "nope" / "nested" / "out"
    resp = client.put(
        "/api/config",
        json={"postprocess_output_dir": str(missing), "delete_raw_after_pack": True},
    )
    assert resp.status_code == 400
    assert "parent directory" in resp.json()["detail"]


def test_put_config_accepts_null_to_clear(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "out"
    client.put(
        "/api/config",
        json={
            "postprocess_output_dir": str(target),
            "delete_raw_after_pack": False,
        },
    )
    resp = client.put(
        "/api/config",
        json={"postprocess_output_dir": None, "delete_raw_after_pack": True},
    )
    assert resp.status_code == 200
    assert resp.json()["postprocess_output_dir"] is None


def test_put_config_trims_whitespace_to_null(client: TestClient) -> None:
    resp = client.put(
        "/api/config",
        json={"postprocess_output_dir": "   ", "delete_raw_after_pack": True},
    )
    assert resp.status_code == 200
    assert resp.json()["postprocess_output_dir"] is None
