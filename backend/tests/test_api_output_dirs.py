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


def test_list_output_dirs_walks_subdirs(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "manga").mkdir()
    (root / "manga" / "ongoing").mkdir()
    (root / "comics").mkdir()
    (root / ".hidden").mkdir()
    _set_root(client, root)

    paths = [e["path"] for e in client.get("/api/output-dirs").json()]
    assert str((root / "manga").resolve()) in paths
    assert str((root / "manga" / "ongoing").resolve()) in paths
    assert str((root / "comics").resolve()) in paths
    assert not any(".hidden" in p for p in paths)


def test_create_output_dir_under_root(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)

    resp = client.post("/api/output-dirs", json={"path": "webtoons"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "webtoons"
    assert (root / "webtoons").is_dir()


def test_create_output_dir_rejects_outside_root(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)
    elsewhere = tmp_path / "elsewhere" / "thing"
    resp = client.post("/api/output-dirs", json={"path": str(elsewhere)})
    assert resp.status_code == 400


def test_create_output_dir_accepts_absolute_under_root(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    _set_root(client, root)
    target = root / "nested" / "deep"
    resp = client.post("/api/output-dirs", json={"path": str(target)})
    assert resp.status_code == 200
    assert target.is_dir()
