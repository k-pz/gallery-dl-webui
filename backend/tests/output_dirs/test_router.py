from pathlib import Path

from fastapi.testclient import TestClient


def _set_root(client: TestClient, root: Path) -> None:
    resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
        },
    )
    assert resp.status_code == 200


def test_list_output_dirs_requires_root(client: TestClient) -> None:
    resp = client.get("/api/output-dirs")
    assert resp.status_code == 400


def test_list_output_dirs_returns_only_direct_children(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "manga").mkdir()
    (root / "manga" / "ongoing").mkdir()
    (root / "comics").mkdir()
    (root / ".hidden").mkdir()
    _set_root(client, root)

    paths = [e["path"] for e in client.get("/api/output-dirs").json()]
    assert str((root / "manga").resolve()) in paths
    assert str((root / "comics").resolve()) in paths
    # Per-series subdirs are intentionally excluded.
    assert str((root / "manga" / "ongoing").resolve()) not in paths
    assert not any(".hidden" in p for p in paths)


def test_create_output_dir_creates_top_level_folder(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)

    resp = client.post("/api/output-dirs", json={"path": "webtoons"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "webtoons"
    assert body["depth"] == 1
    assert (root / "webtoons").is_dir()


def test_create_output_dir_rejects_outside_root(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)
    elsewhere = tmp_path / "elsewhere" / "thing"
    resp = client.post("/api/output-dirs", json={"path": str(elsewhere)})
    assert resp.status_code == 400


def test_create_output_dir_rejects_nested_path(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)
    resp = client.post("/api/output-dirs", json={"path": "manga/new-series"})
    assert resp.status_code == 400


def test_create_output_dir_rejects_absolute_deeper_path(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)
    resp = client.post("/api/output-dirs", json={"path": str(root / "nested" / "deep")})
    assert resp.status_code == 400


def test_create_output_dir_accepts_absolute_direct_child(
    client: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)
    target = root / "library"
    resp = client.post("/api/output-dirs", json={"path": str(target)})
    assert resp.status_code == 200
    assert target.is_dir()


def test_list_output_dirs_omits_configured_exclusions(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "manga").mkdir()
    (root / "#recycle").mkdir()
    (root / "@eaDir").mkdir()
    _set_root(client, root)

    names = [e["name"] for e in client.get("/api/output-dirs").json()]
    assert "manga" in names
    # Defaults pulled from DEFAULT_EXCLUDED_DIR_NAMES — Synology recycle bin
    # and the @eaDir indexer dir — never reach the picker.
    assert "#recycle" not in names
    assert "@eaDir" not in names
