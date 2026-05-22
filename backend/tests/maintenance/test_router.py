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


def test_regenerate_series_metadata_picks_up_target_series_status(
    client: TestClient, tmp_path: Path, gallery_config
) -> None:
    """A series_status on the target row should land in the regen'd series.json
    via `_build_series_overrides` (which keys by sanitised target name)."""
    import json

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
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()
    # Force the sim pass to claim "Series" as the name so the regen override
    # key (sanitize(target.name)) matches the on-disk directory.
    gallery_config.manifest_for["https://example/x"] = []
    gallery_config.series_name_for["https://example/x"] = "Series"
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200, sub.json()
    for _ in range(40):
        targets = client.get("/api/targets").json()
        if targets and targets[0]["name"] == "Series":
            break
        time.sleep(0.05)
    target_id = client.get("/api/targets").json()[0]["id"]
    client.patch(f"/api/targets/{target_id}", json={"series_status": "Hiatus"})

    created = client.post("/api/maintenance/jobs", json={"kind": "regenerate_series_metadata"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done

    payload = json.loads((series_dir / "series.json").read_text())
    assert payload["metadata"]["status"] == "Hiatus"


def _read_comicinfo(cbz: Path) -> dict[str, str]:
    """Return the ComicInfo.xml fields written into `cbz` as a plain dict."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(cbz) as zf:
        root = ET.fromstring(zf.read("ComicInfo.xml"))
    return {el.tag: el.text or "" for el in root}


def test_regenerate_rediscovers_series_metadata_via_gallery(
    client: TestClient, tmp_path: Path, gallery_config
) -> None:
    """Regen runs a metadata-only sim against each target's URL and applies
    rediscovered status/tags/chapter-dates to series.json + ComicInfo.xml."""
    import json
    from datetime import datetime

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
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()

    # Initial download surfaces neither status nor tags from the sim, so the
    # target row starts with both blank — leaving room for the regen-time
    # rediscovery to fill them.
    gallery_config.manifest_for["https://example/x"] = []
    gallery_config.series_name_for["https://example/x"] = "Series"
    sub = client.post(
        "/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)}
    )
    assert sub.status_code == 200, sub.json()
    for _ in range(40):
        targets = client.get("/api/targets").json()
        if targets and targets[0]["name"] == "Series":
            break
        time.sleep(0.05)
    target_id = client.get("/api/targets").json()[0]["id"]

    # Now upstream "discovers" status + tags + a chapter date. The regen pass
    # should pick all three up via extract_metadata.
    gallery_config.series_status_for["https://example/x"] = "Hiatus"
    gallery_config.series_tags_for["https://example/x"] = ["Action", "Drama"]
    gallery_config.chapter_dates_for["https://example/x"] = {
        ("Series", "1"): "2025-03-14",
    }

    created = client.post("/api/maintenance/jobs", json={"kind": "regenerate_series_metadata"})
    job_id = created.json()["id"]
    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done

    payload = json.loads((series_dir / "series.json").read_text())
    assert payload["metadata"]["status"] == "Hiatus"
    assert payload["metadata"]["tags"] == ["Action", "Drama"]

    target = client.get(f"/api/targets/{target_id}").json()
    assert target["series_status"] == "Hiatus"
    assert target["tags"] == ["Action", "Drama"]

    ci = _read_comicinfo(series_dir / "Series - c001.cbz")
    assert ci["Year"] == "2025"
    assert ci["Month"] == "3"
    assert ci["Day"] == "14"
    assert ci["Tags"] == "Action, Drama"
    # Sanity: the date we wrote at CBZ-creation time was blank; the regen
    # backfilled it from the rediscovery pass.
    assert datetime(2025, 3, 14).strftime("%Y") == ci["Year"]


def test_regenerate_does_not_overwrite_user_set_series_status_or_tags(
    client: TestClient, tmp_path: Path, gallery_config
) -> None:
    """User-set status/tags survive a rediscovery pass that surfaces different
    values (fill-only contract still applies during regen)."""
    import json

    root = tmp_path / "media"
    output_dir = root / "Manga"
    series_dir = output_dir / "Series"
    _write_cbz(series_dir / "Series - c001.cbz", "Series", "1")

    client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
            "chapter_naming_template": "{{ series }} - c{{ chapter_number }}",
        },
    )
    gallery_config.manifest_for["https://example/x"] = []
    gallery_config.series_name_for["https://example/x"] = "Series"
    client.post("/api/downloads", json={"url": "https://example/x", "output_dir": str(output_dir)})
    for _ in range(40):
        targets = client.get("/api/targets").json()
        if targets and targets[0]["name"] == "Series":
            break
        time.sleep(0.05)
    target_id = client.get("/api/targets").json()[0]["id"]
    # User pins both fields manually.
    client.patch(
        f"/api/targets/{target_id}",
        json={"series_status": "Ended", "tags": ["Romance"]},
    )

    # Rediscovery would otherwise want to write a different status + tags.
    gallery_config.series_status_for["https://example/x"] = "Ongoing"
    gallery_config.series_tags_for["https://example/x"] = ["Action"]

    created = client.post("/api/maintenance/jobs", json={"kind": "regenerate_series_metadata"})
    done = _wait_for_completion(client, created.json()["id"])
    assert done["status"] == "completed", done

    payload = json.loads((series_dir / "series.json").read_text())
    assert payload["metadata"]["status"] == "Ended"
    assert payload["metadata"]["tags"] == ["Romance"]


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


def test_push_komga_status_missing_params_is_rejected(client: TestClient) -> None:
    resp = client.post("/api/maintenance/jobs", json={"kind": "push_komga_series_status"})
    assert resp.status_code == 400
    assert "params" in resp.json()["detail"]


def test_push_komga_status_blank_field_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/maintenance/jobs",
        json={
            "kind": "push_komga_series_status",
            "params": {"base_url": "http://k", "username": "u", "password": ""},
        },
    )
    assert resp.status_code == 400
    assert "password" in resp.json()["detail"]


def test_push_komga_status_bad_base_url_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/maintenance/jobs",
        json={
            "kind": "push_komga_series_status",
            "params": {"base_url": "ftp://nope", "username": "u", "password": "p"},
        },
    )
    assert resp.status_code == 400


def test_push_komga_status_end_to_end(
    client: TestClient, tmp_path: Path, gallery_config, monkeypatch
) -> None:
    """Schedule the job and watch it push a target's status to a fake Komga.

    We swap `httpx.AsyncClient` for one backed by `MockTransport` so the worker
    talks to an in-process fake. The schedule request still carries real-looking
    credentials so the validation path runs.
    """
    import httpx

    # Stage a target with a series_status set.
    cfg_resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(tmp_path / "media"),
            "postprocess_default_output_dir": None,
            "delete_raw_after_pack": True,
            "default_watch_period": "1d",
        },
    )
    assert cfg_resp.status_code == 200, cfg_resp.json()
    gallery_config.series_name_for["https://example/x"] = "Series"
    gallery_config.manifest_for["https://example/x"] = []
    sub = client.post("/api/downloads", json={"url": "https://example/x"})
    assert sub.status_code == 200
    for _ in range(40):
        targets = client.get("/api/targets").json()
        if targets and targets[0]["name"] == "Series":
            break
        time.sleep(0.05)
    target_id = client.get("/api/targets").json()[0]["id"]
    client.patch(f"/api/targets/{target_id}", json={"series_status": "Hiatus"})

    patches: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/series":
            assert request.url.params.get("search") == "Series"
            return httpx.Response(200, json={"content": [{"id": "k-series-id", "name": "Series"}]})
        if request.method == "PATCH":
            import json

            patches.append((request.url.path, json.loads(request.content)["status"]))
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    # The Komga helper constructs `httpx.AsyncClient(...)` lazily, so patching
    # the class on the httpx module before scheduling the job is enough.
    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    created = client.post(
        "/api/maintenance/jobs",
        json={
            "kind": "push_komga_series_status",
            "params": {
                "base_url": "http://komga.local",
                "username": "user",
                "password": "pw",
            },
        },
    )
    assert created.status_code == 200, created.json()
    job_id = created.json()["id"]

    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done
    assert done["result"]["updated"] == 1
    assert patches == [("/api/v1/series/k-series-id/metadata", "HIATUS")]


def test_update_lxc_writes_trigger_when_path_unit_enabled(
    client: TestClient, settings, monkeypatch
) -> None:
    """update_lxc should drop the trigger file inside DATA_DIR and complete."""
    from backend.maintenance import worker as worker_mod

    monkeypatch.setattr(worker_mod, "_update_path_unit_enabled", lambda: True)

    created = client.post("/api/maintenance/jobs", json={"kind": "update_lxc"})
    assert created.status_code == 200, created.json()
    job_id = created.json()["id"]

    done = _wait_for_completion(client, job_id)
    assert done["status"] == "completed", done
    assert done["result"]["status"] == "kicked_off"

    trigger = settings.data_dir / worker_mod.UPDATE_TRIGGER_FILENAME
    assert trigger.is_file(), f"expected trigger at {trigger}"
    assert trigger.read_text(encoding="utf-8") == "requested\n"


def test_update_lxc_fails_when_path_unit_not_enabled(
    client: TestClient, settings, monkeypatch
) -> None:
    """No path unit installed → job fails fast instead of leaving a stale file."""
    from backend.maintenance import worker as worker_mod

    monkeypatch.setattr(worker_mod, "_update_path_unit_enabled", lambda: False)

    created = client.post("/api/maintenance/jobs", json={"kind": "update_lxc"})
    assert created.status_code == 200, created.json()
    job_id = created.json()["id"]

    done = _wait_for_completion(client, job_id)
    assert done["status"] == "failed", done
    assert "update infrastructure not installed" in (done["error"] or "")
    assert not (settings.data_dir / worker_mod.UPDATE_TRIGGER_FILENAME).exists()


def test_update_lxc_unsupported_when_kind_typoed(client: TestClient) -> None:
    """Unknown kinds still 400 — confirms update_lxc is allowlisted, not a regex."""
    resp = client.post("/api/maintenance/jobs", json={"kind": "update_xyz"})
    assert resp.status_code == 400
