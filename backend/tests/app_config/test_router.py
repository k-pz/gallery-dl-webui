from pathlib import Path

from fastapi.testclient import TestClient

from backend.app_config.constants import DEFAULT_CHAPTER_NAMING_TEMPLATE


def _put(client: TestClient, **fields):
    body = {
        "postprocess_root": None,
        "postprocess_default_output_dir": None,
        "delete_raw_after_pack": True,
        "chapter_naming_template": None,
    }
    body.update(fields)
    return client.put("/api/config", json=body)


def test_get_config_returns_defaults(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["postprocess_root"] is None
    assert body["postprocess_default_output_dir"] is None
    assert body["postprocess_known_output_dirs"] == []
    assert body["delete_raw_after_pack"] is True
    assert body["chapter_naming_template"] == DEFAULT_CHAPTER_NAMING_TEMPLATE


def test_put_config_persists_root_and_default(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    default = root / "manga"
    resp = _put(
        client,
        postprocess_root=str(root),
        postprocess_default_output_dir=str(default),
        delete_raw_after_pack=False,
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["postprocess_root"] == str(root.resolve())
    assert body["postprocess_default_output_dir"] == str(default.resolve())
    assert body["delete_raw_after_pack"] is False
    assert root.is_dir()
    assert default.is_dir()

    follow = client.get("/api/config").json()
    assert follow["postprocess_root"] == str(root.resolve())
    assert follow["postprocess_default_output_dir"] == str(default.resolve())


def test_put_config_persists_chapter_naming_template(client: TestClient) -> None:
    tpl = "{{ series }}_ch{{ chapter_number }}"
    resp = _put(client, chapter_naming_template=tpl)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["chapter_naming_template"] == tpl
    assert client.get("/api/config").json()["chapter_naming_template"] == tpl


def test_put_config_rejects_invalid_chapter_template(client: TestClient) -> None:
    resp = _put(client, chapter_naming_template="{{ missing_name }}")
    assert resp.status_code == 400
    assert "invalid chapter_naming_template" in resp.json()["detail"]


def test_put_config_rejects_relative_root(client: TestClient) -> None:
    resp = _put(client, postprocess_root="relative/dir")
    assert resp.status_code == 400
    assert "absolute path" in resp.json()["detail"]


def test_put_config_rejects_default_outside_root(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    outside = tmp_path / "other" / "manga"
    resp = _put(
        client,
        postprocess_root=str(root),
        postprocess_default_output_dir=str(outside),
    )
    assert resp.status_code == 400
    assert "under root" in resp.json()["detail"]


def test_put_config_rejects_default_without_root(client: TestClient, tmp_path: Path) -> None:
    resp = _put(
        client,
        postprocess_root=None,
        postprocess_default_output_dir=str(tmp_path / "manga"),
    )
    assert resp.status_code == 400
    assert "requires postprocess_root" in resp.json()["detail"]


def test_put_config_accepts_null_to_clear(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    _put(
        client,
        postprocess_root=str(root),
        postprocess_default_output_dir=str(root / "manga"),
    )
    resp = _put(client, postprocess_root=None, postprocess_default_output_dir=None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["postprocess_root"] is None
    assert body["postprocess_default_output_dir"] is None


def test_put_config_trims_whitespace_to_null(client: TestClient) -> None:
    resp = _put(client, postprocess_root="   ", postprocess_default_output_dir="   ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["postprocess_root"] is None
    assert body["postprocess_default_output_dir"] is None


def test_get_config_defaults_reading_direction(client: TestClient) -> None:
    assert client.get("/api/config").json()["default_reading_direction"] == "ltr"


def test_put_config_persists_default_reading_direction(client: TestClient) -> None:
    resp = _put(client, default_reading_direction="rtl")
    assert resp.status_code == 200, resp.json()
    assert resp.json()["default_reading_direction"] == "rtl"
    assert client.get("/api/config").json()["default_reading_direction"] == "rtl"


def test_put_config_rejects_invalid_reading_direction(client: TestClient) -> None:
    resp = _put(client, default_reading_direction="diagonal")
    assert resp.status_code == 400


def test_changing_root_clears_known_dirs(client: TestClient, tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    # Configure root A and submit a download with an output dir under it.
    _put(client, postprocess_root=str(root_a))
    sub = client.post(
        "/api/downloads",
        json={"url": "https://example/x", "output_dir": str(root_a / "comics")},
    )
    assert sub.status_code == 200, sub.json()
    cfg = client.get("/api/config").json()
    assert any("comics" in d for d in cfg["postprocess_known_output_dirs"])

    # Switching root drops the remembered list.
    resp = _put(client, postprocess_root=str(root_b))
    assert resp.status_code == 200
    assert resp.json()["postprocess_known_output_dirs"] == []


def test_get_config_surfaces_default_excluded_dir_names(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    assert "#recycle" in cfg["postprocess_excluded_dir_names"]


def test_put_config_persists_excluded_dir_names(client: TestClient, tmp_path: Path) -> None:
    resp = _put(
        client,
        postprocess_excluded_dir_names=["#recycle", "  @eaDir  ", "", "#recycle"],
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    # Whitespace is stripped, blanks dropped, dedup preserved-order.
    assert body["postprocess_excluded_dir_names"] == ["#recycle", "@eaDir"]
    follow = client.get("/api/config").json()
    assert follow["postprocess_excluded_dir_names"] == ["#recycle", "@eaDir"]
