import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.downloads.postprocess import ChapterRecord, build_comicinfo_xml


def _write_cbz(path: Path, series: str, chapter: str, title: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ch = ChapterRecord(
        manga=series,
        chapter=chapter,
        title=title,
        volume="",
        lang="",
        author="",
        date="",
        dir=path.parent,
        pages=[Path("/x/001.jpg")],
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ComicInfo.xml", build_comicinfo_xml(ch))
        zf.writestr("001.jpg", b"x")


def _wait_for_completion(client: TestClient, job_id: int) -> dict[str, object]:
    for _ in range(30):
        jobs = client.get("/api/maintenance/jobs").json()
        current = next((j for j in jobs if j["id"] == job_id), None)
        if current and current["status"] in ("completed", "failed"):
            return current
        time.sleep(0.05)
    raise AssertionError("maintenance job did not finish in time")


def test_schedule_rename_chapters_job(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Series"
    old = series_dir / "Series - c001.cbz"
    _write_cbz(old, "Series", "1")

    cfg_resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
            "chapter_naming_template": "{{ series }}_{{ chapter_number }}",
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    assert created.status_code == 200, created.json()
    job_id = created.json()["id"]

    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed"
    assert done["result"]["renamed"] == 1
    assert (series_dir / "Series_001.cbz").is_file()
    assert not old.exists()


def test_rename_keeps_archives_in_their_source_directory(
    client: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "media"
    nested = root / "custom-output" / "Series"
    old = nested / "Series - c001.cbz"
    _write_cbz(old, "Series", "1")

    cfg_resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
            "chapter_naming_template": "{{ series }}_{{ chapter_number }}",
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed"
    # The file is renamed *in place* — it must not jump to <root>/<series>/.
    assert (nested / "Series_001.cbz").is_file()
    assert not (root / "Series" / "Series_001.cbz").exists()


def test_progress_endpoint_for_terminal_job(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Series"
    _write_cbz(series_dir / "Series - c001.cbz", "Series", "1")

    cfg_resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
            "chapter_naming_template": "{{ series }}_{{ chapter_number }}",
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed"

    resp = client.get(f"/api/maintenance/jobs/{job_id}/progress")
    assert resp.status_code == 200, resp.json()
    payload = resp.json()
    assert payload["status"] == "completed"
    # Worker clears the in-memory tail once a job terminates; a synthetic
    # summary line is included so callers always have something to render.
    assert payload["lines"], payload
    assert any("done" in line for line in payload["lines"])


def test_progress_endpoint_missing_job(client: TestClient) -> None:
    resp = client.get("/api/maintenance/jobs/9999/progress")
    assert resp.status_code == 404


def test_schedule_regenerate_series_metadata_job(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Series"
    _write_cbz(series_dir / "Series - c001.cbz", "Series", "1")

    cfg_resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
            "chapter_naming_template": "{{ series }} - c{{ chapter_number }}",
            "default_reading_direction": "rtl",
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "regenerate_series_metadata"})
    assert created.status_code == 200, created.json()
    job_id = created.json()["id"]

    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done
    assert done["result"]["archives_updated"] == 1
    assert done["result"]["series_json_written"] == 1
    # series.json was emitted next to the CBZ.
    assert (series_dir / "series.json").is_file()


def test_unsupported_maintenance_kind_is_rejected(client: TestClient) -> None:
    resp = client.post("/api/maintenance/jobs", json={"kind": "nonexistent"})
    assert resp.status_code == 400


def test_cancel_pending_maintenance_job(client: TestClient, tmp_path: Path) -> None:
    """Flipping a still-pending row to cancelled before the worker claims it.

    The worker has nothing to schedule (no root configured), so the job stays
    pending long enough to be cancelled directly.
    """
    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    assert created.status_code == 200, created.json()
    job_id = created.json()["id"]

    resp = client.post(f"/api/maintenance/jobs/{job_id}/cancel")
    # Race: the worker may have already claimed the job and failed it
    # (postprocess_root unset). Either outcome is acceptable from the cancel
    # endpoint as long as the terminal status sticks.
    assert resp.status_code in (200, 409), resp.json()
    final = next(j for j in client.get("/api/maintenance/jobs").json() if j["id"] == job_id)
    assert final["status"] in ("cancelled", "failed")


def test_cancel_terminal_job_is_rejected(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    series_dir = root / "Series"
    _write_cbz(series_dir / "Series - c001.cbz", "Series", "1")

    cfg_resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
            "chapter_naming_template": "{{ series }}_{{ chapter_number }}",
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed"

    resp = client.post(f"/api/maintenance/jobs/{job_id}/cancel")
    assert resp.status_code == 409


def test_cancel_missing_job_is_404(client: TestClient) -> None:
    resp = client.post("/api/maintenance/jobs/9999/cancel")
    assert resp.status_code == 404
