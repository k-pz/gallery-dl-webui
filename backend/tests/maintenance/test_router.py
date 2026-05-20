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
        if current and current["status"] in ("completed", "failed", "cancelled"):
            return current
        time.sleep(0.05)
    raise AssertionError("maintenance job did not finish in time")


def test_schedule_rename_chapters_job(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    output_dir = root / "Manga"
    series_dir = output_dir / "Series"
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
    # Maintenance is scoped to the output dirs targets actually use, so stage a
    # target whose output_dir contains the CBZ we want renamed.
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200, sub.json()

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
    output_dir = root / "custom-output"
    nested = output_dir / "Series"
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
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200, sub.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed"
    # The file is renamed *in place* — it must not jump to <root>/<series>/.
    assert (nested / "Series_001.cbz").is_file()
    assert not (root / "Series" / "Series_001.cbz").exists()


def test_progress_endpoint_for_terminal_job(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    output_dir = root / "Manga"
    series_dir = output_dir / "Series"
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
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200, sub.json()

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
    output_dir = root / "Manga"
    series_dir = output_dir / "Series"
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
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200, sub.json()

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
    final = _wait_for_completion(client, job_id)
    assert final["status"] in ("cancelled", "failed")


def test_cancel_terminal_job_is_rejected(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "media"
    output_dir = root / "Manga"
    series_dir = output_dir / "Series"
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
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200, sub.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed"

    resp = client.post(f"/api/maintenance/jobs/{job_id}/cancel")
    assert resp.status_code == 409


def test_cancel_missing_job_is_404(client: TestClient) -> None:
    resp = client.post("/api/maintenance/jobs/9999/cancel")
    assert resp.status_code == 404


def test_rebuild_library_wipes_and_reenqueues(
    client: TestClient, tmp_path: Path, gallery_config
) -> None:
    """End-to-end: a target + one finished download → rebuild wipes the
    target's designated output dir and re-enqueues a fresh pending row.

    A `#recycle` directory and an unrelated sibling directory both live next to
    the output dir; the rebuild must spare them. The output dir itself
    contains its own `#recycle` to also confirm the in-dir exclusion path.
    """
    root = tmp_path / "media"
    root.mkdir()
    output_dir = root / "Manga"
    series_dir = output_dir / "Series"
    _write_cbz(series_dir / "Series - c001.cbz", "Series", "1")
    # `#recycle` sits inside the output dir so the wipe encounters it directly.
    recycle = output_dir / "#recycle"
    recycle.mkdir()
    (recycle / "marker.txt").write_text("keep me")
    # An unrelated directory sitting under root but outside any designated
    # output dir — this is what the bug report was about. It must survive.
    unrelated = root / "Family Photos"
    unrelated.mkdir()
    (unrelated / "irreplaceable.txt").write_text("priceless")

    cfg_resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
            "chapter_naming_template": "{{ series }}_{{ chapter_number }}",
            "postprocess_excluded_dir_names": ["#recycle"],
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()

    gallery_config.manifest_for["https://example/x"] = []
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200

    created = client.post("/api/maintenance/jobs", json={"kind": "rebuild_library"})
    assert created.status_code == 200, created.json()
    job_id = created.json()["id"]

    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done
    assert done["result"]["targets"] >= 1
    assert done["result"]["enqueued"] >= 1
    # Designated output dir wiped...
    assert not (output_dir / "Series").exists()
    # ...but the excluded recycle bin inside it survives...
    assert (recycle / "marker.txt").read_text() == "keep me"
    # ...and content sitting under root outside any designated dir is untouched.
    assert (unrelated / "irreplaceable.txt").read_text() == "priceless"


def test_rename_ignores_archives_outside_designated_output_dirs(
    client: TestClient, tmp_path: Path
) -> None:
    """A CBZ sitting in a root subdir that no target has designated as its
    output_dir must not be touched by the rename job — regression for the
    "maintenance walks the whole root" bug.
    """
    root = tmp_path / "media"
    designated = root / "Manga"
    unrelated_dir = root / "Borrowed Library"
    target_cbz = designated / "Series" / "Series - c001.cbz"
    other_cbz = unrelated_dir / "Other Series" / "Other Series - c001.cbz"
    _write_cbz(target_cbz, "Series", "1")
    _write_cbz(other_cbz, "Other Series", "1")

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
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(designated)}
    )
    assert sub.status_code == 200, sub.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "rename_chapters"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done

    # The designated archive got renamed; the unrelated one is left exactly
    # where it was, with its original filename intact.
    assert (designated / "Series" / "Series_001.cbz").is_file()
    assert other_cbz.is_file()
    assert not (unrelated_dir / "Other Series" / "Other Series_001.cbz").exists()


def test_regenerate_metadata_ignores_archives_outside_designated_output_dirs(
    client: TestClient, tmp_path: Path
) -> None:
    """series.json must only land next to archives in a designated output dir."""
    root = tmp_path / "media"
    designated = root / "Manga"
    unrelated_dir = root / "Borrowed Library" / "Other Series"
    _write_cbz(designated / "Series" / "Series - c001.cbz", "Series", "1")
    _write_cbz(unrelated_dir / "Other Series - c001.cbz", "Other Series", "1")

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
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(designated)}
    )
    assert sub.status_code == 200, sub.json()

    created = client.post("/api/maintenance/jobs", json={"kind": "regenerate_series_metadata"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done
    assert done["result"]["archives_updated"] == 1
    assert done["result"]["series_json_written"] == 1

    assert (designated / "Series" / "series.json").is_file()
    assert not (unrelated_dir / "series.json").exists()
