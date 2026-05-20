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
