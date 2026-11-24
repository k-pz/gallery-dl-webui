import json
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.config import Settings
from tests._helpers import write_chapter_cbz

SERIES = "My Series"
URL = "https://example/my-series"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


@pytest.fixture
def library(client: TestClient, tmp_path: Path) -> Path:
    """Configure a postprocess root and import one named series; returns its
    series directory (where the packer would write CBZs)."""
    root = tmp_path / "media"
    out = root / "manga"
    resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(root),
            "postprocess_default_output_dir": str(out),
            "delete_raw_after_pack": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = yaml.safe_dump(
        {
            "version": 1,
            "series": [
                {"url": URL, "name": SERIES, "tags": ["Action"], "reading_direction": "rtl"}
            ],
        }
    )
    resp = client.post(
        "/api/library/import", content=body, headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 200, resp.text
    return out.resolve() / SERIES


def _target_id(client: TestClient) -> int:
    return next(t["id"] for t in client.get("/api/targets").json() if t["url"] == URL)


def _overview(client: TestClient) -> dict[str, Any]:
    resp = client.get(f"/api/targets/{_target_id(client)}/epub")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _put_books(client: TestClient, books: list[dict[str, Any]]):
    return client.put(f"/api/targets/{_target_id(client)}/epub/books", json={"books": books})


def _write_chapters(series_dir: Path, numbers: list[str], volumes: dict[str, str] | None = None):
    for n in numbers:
        write_chapter_cbz(
            series_dir / f"{SERIES} - c{n}.cbz",
            SERIES,
            n,
            title=f"Title {n}",
            volume=(volumes or {}).get(n, ""),
            author="Writer",
            lang="en",
        )


def test_overview_lists_chapters_and_volume_suggestion(
    client: TestClient, library: Path, settings: Settings
) -> None:
    _write_chapters(library, ["1", "2", "3", "4"], volumes={"1": "1", "2": "1", "3": "2"})
    body = _overview(client)
    assert body["series"] == SERIES
    assert body["series_dir"] == str(library)
    assert body["export_dir"] == str(settings.data_dir / "epub")
    assert [c["number"] for c in body["chapters"]] == ["1", "2", "3", "4"]
    assert body["chapters"][0]["title"] == "Title 1"
    assert body["books"] == []
    assert body["unassigned"] == ["1", "2", "3", "4"]
    assert body["suggested_books"] == [
        {"title": None, "chapter_start": 1.0},
        {"title": None, "chapter_start": 3.0},
        {"title": None, "chapter_start": 4.0},
    ]


def test_overview_for_series_without_name_is_empty(client: TestClient) -> None:
    client.post(
        "/api/library/import",
        content=yaml.safe_dump({"version": 1, "series": [{"url": URL}]}),
        headers={"content-type": "application/yaml"},
    )
    body = _overview(client)
    assert body["series"] is None
    assert body["series_dir"] is None
    assert body["chapters"] == []


def test_overview_unknown_target_404(client: TestClient) -> None:
    assert client.get("/api/targets/999/epub").status_code == 404


def test_put_books_assigns_chapters_in_order(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1", "2", "3", "7"])
    resp = _put_books(
        client,
        [
            {"chapter_start": 3, "title": "  "},
            {"chapter_start": 1, "title": "Beginnings"},
        ],
    )
    assert resp.status_code == 200, resp.text
    books = resp.json()["books"]
    assert [(b["position"], b["chapter_start"]) for b in books] == [(1, 1.0), (2, 3.0)]
    assert books[0]["title"] == "Beginnings"
    assert books[0]["custom_title"] == "Beginnings"
    assert books[1]["title"] == f"{SERIES}, Vol. 2"
    assert books[1]["custom_title"] is None
    assert [b["chapter_count"] for b in books] == [2, 2]
    assert (books[1]["first_chapter"], books[1]["last_chapter"]) == ("3", "7")
    assert [b["status"] for b in books] == ["not_exported", "not_exported"]
    assert resp.json()["unassigned"] == []
    positions = {c["number"]: c["book_position"] for c in resp.json()["chapters"]}
    assert positions == {"1": 1, "2": 1, "3": 2, "7": 2}


def test_put_books_puts_every_numbered_chapter_in_a_book(client: TestClient, library: Path) -> None:
    # Chapters below the first start join the first book; later chapters
    # join the last (open) book; only non-numeric chapters stay unassigned.
    _write_chapters(library, ["0.5", "1", "4", "9", "Extra"])
    body = _put_books(client, [{"chapter_start": 1}, {"chapter_start": 5}]).json()
    positions = {c["number"]: c["book_position"] for c in body["chapters"]}
    assert positions == {"0.5": 1, "1": 1, "4": 1, "9": 2, "Extra": None}
    assert body["unassigned"] == ["Extra"]


def test_put_books_ignores_legacy_chapter_end(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1", "2", "3"])
    body = _put_books(client, [{"chapter_start": 1, "chapter_end": 1}]).json()
    assert body["books"][0]["chapter_count"] == 3


def test_put_books_rejects_duplicate_starts(client: TestClient, library: Path) -> None:
    resp = _put_books(client, [{"chapter_start": 1}, {"chapter_start": 1}])
    assert resp.status_code == 400
    assert "two books start at chapter 1" in resp.json()["detail"]


def test_export_writes_epub_with_series_metadata(
    client: TestClient, library: Path, settings: Settings
) -> None:
    _write_chapters(library, ["1", "2", "3"])
    books = _put_books(client, [{"chapter_start": 1}, {"chapter_start": 3}])
    first = books.json()["books"][0]
    tid = _target_id(client)

    resp = client.post(f"/api/targets/{tid}/epub/books/{first['id']}/export")
    assert resp.status_code == 200, resp.text
    exported = resp.json()["books"][0]
    assert exported["status"] == "exported"
    assert exported["file_name"] == f"{SERIES} - Vol. 01.epub"
    assert exported["exported_at"] is not None
    assert resp.json()["books"][1]["status"] == "not_exported"

    path = settings.data_dir / "epub" / SERIES / f"{SERIES} - Vol. 01.epub"
    with zipfile.ZipFile(path) as zf:
        opf = ET.fromstring(zf.read("OEBPS/content.opf"))
        page_count = sum(1 for n in zf.namelist() if n.startswith("OEBPS/pages/"))
    md = opf.find("opf:metadata", OPF_NS)
    assert md is not None
    assert md.findtext("dc:title", namespaces=OPF_NS) == f"{SERIES}, Vol. 1"
    assert md.findtext("dc:creator", namespaces=OPF_NS) == "Writer"
    assert md.findtext("dc:language", namespaces=OPF_NS) == "en"
    assert [s.text for s in md.findall("dc:subject", OPF_NS)] == ["Action"]
    named = {m.get("name"): m.get("content") for m in md.findall("opf:meta", OPF_NS)}
    assert named["calibre:series"] == SERIES
    assert named["calibre:series_index"] == "1"
    spine = opf.find("opf:spine", OPF_NS)
    assert spine is not None
    assert spine.get("page-progression-direction") == "rtl"
    assert page_count == 2


def test_new_chapter_marks_export_outdated(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1", "2"])
    book = _put_books(client, [{"chapter_start": 1}]).json()["books"][0]
    tid = _target_id(client)
    client.post(f"/api/targets/{tid}/epub/books/{book['id']}/export")
    assert _overview(client)["books"][0]["status"] == "exported"

    _write_chapters(library, ["3"])
    assert _overview(client)["books"][0]["status"] == "outdated"


def test_resaving_unchanged_range_keeps_export_record(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1", "2"])
    book = _put_books(client, [{"chapter_start": 1}]).json()["books"][0]
    tid = _target_id(client)
    client.post(f"/api/targets/{tid}/epub/books/{book['id']}/export")

    resaved = _put_books(client, [{"chapter_start": 1}]).json()["books"][0]
    assert resaved["status"] == "exported"
    retitled = _put_books(client, [{"chapter_start": 1, "title": "New"}])
    assert retitled.json()["books"][0]["status"] == "outdated"


def test_export_all_exports_pending_books_and_skips_current(
    client: TestClient, library: Path, settings: Settings
) -> None:
    _write_chapters(library, ["1", "2", "3"])
    _put_books(
        client,
        [{"chapter_start": 1}, {"chapter_start": 2}, {"chapter_start": 10}],
    )
    tid = _target_id(client)
    resp = client.post(f"/api/targets/{tid}/epub/export")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"exported": 2, "failed": 0, "errors": []}
    assert [b["status"] for b in _overview(client)["books"]] == ["exported", "exported", "empty"]

    again = client.post(f"/api/targets/{tid}/epub/export").json()
    assert again == {"exported": 0, "failed": 0, "errors": []}


def test_export_all_reports_failures_per_book(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1"])
    # A chapter archive with ComicInfo but no pages fails its book only.
    write_chapter_cbz(library / f"{SERIES} - c002.cbz", SERIES, "2", pages=[])
    _put_books(client, [{"chapter_start": 1}, {"chapter_start": 2}])
    resp = client.post(f"/api/targets/{_target_id(client)}/epub/export").json()
    assert resp["exported"] == 1
    assert resp["failed"] == 1
    assert "no page images" in resp["errors"][0]


def test_export_empty_book_conflicts(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1"])
    book = _put_books(client, [{"chapter_start": 1}, {"chapter_start": 5}]).json()["books"][1]
    resp = client.post(f"/api/targets/{_target_id(client)}/epub/books/{book['id']}/export")
    assert resp.status_code == 409


def test_export_unknown_book_404(client: TestClient, library: Path) -> None:
    resp = client.post(f"/api/targets/{_target_id(client)}/epub/books/999/export")
    assert resp.status_code == 404


def test_download_serves_exported_file(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1"])
    book = _put_books(client, [{"chapter_start": 1}]).json()["books"][0]
    tid = _target_id(client)
    assert client.get(f"/api/targets/{tid}/epub/books/{book['id']}/file").status_code == 404

    client.post(f"/api/targets/{tid}/epub/books/{book['id']}/export")
    resp = client.get(f"/api/targets/{tid}/epub/books/{book['id']}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/epub+zip"
    # Non-ASCII-safe RFC 5987 form: filename*=utf-8''<percent-encoded>.
    assert "My%20Series%20-%20Vol.%2001.epub" in resp.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(resp.content)) as zf:
        assert zf.read("mimetype") == b"application/epub+zip"


def test_renumbered_book_moves_its_export(
    client: TestClient, library: Path, settings: Settings
) -> None:
    _write_chapters(library, ["1", "2", "3"])
    book = _put_books(client, [{"chapter_start": 2}]).json()["books"][0]
    tid = _target_id(client)
    client.post(f"/api/targets/{tid}/epub/books/{book['id']}/export")
    series_out = settings.data_dir / "epub" / SERIES
    assert (series_out / f"{SERIES} - Vol. 01.epub").is_file()

    # Insert a book in front: the old book becomes Vol. 2 and is outdated.
    books = _put_books(client, [{"chapter_start": 1}, {"chapter_start": 2}])
    moved = books.json()["books"][1]
    assert moved["status"] == "outdated"

    client.post(f"/api/targets/{tid}/epub/books/{moved['id']}/export")
    assert (series_out / f"{SERIES} - Vol. 02.epub").is_file()
    # The stale Vol. 01 file (old content) is cleaned up.
    assert not (series_out / f"{SERIES} - Vol. 01.epub").exists()
    assert _overview(client)["books"][0]["status"] == "not_exported"


def test_export_uses_configured_export_dir(
    client: TestClient, library: Path, tmp_path: Path
) -> None:
    calibre = tmp_path / "calibre-in"
    resp = client.put(
        "/api/config",
        json={
            "postprocess_root": str(library.parent.parent),
            "postprocess_default_output_dir": str(library.parent),
            "delete_raw_after_pack": True,
            "epub_export_dir": str(calibre),
        },
    )
    assert resp.status_code == 200, resp.text
    _write_chapters(library, ["1"])
    book = _put_books(client, [{"chapter_start": 1}]).json()["books"][0]
    client.post(f"/api/targets/{_target_id(client)}/epub/books/{book['id']}/export")
    assert (calibre.resolve() / SERIES / f"{SERIES} - Vol. 01.epub").is_file()


def test_deleting_target_removes_its_books(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1"])
    _put_books(client, [{"chapter_start": 1}])
    tid = _target_id(client)
    assert client.delete(f"/api/targets/{tid}").status_code == 200
    assert client.get(f"/api/targets/{tid}/epub").status_code == 404


def test_mutations_emit_epub_events(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1"])
    tid = _target_id(client)
    resp = _put_books(client, [{"chapter_start": 1}])
    expected = {"topic": "epub", "type": "updated", "data": {"target_id": tid}}
    assert expected in json.loads(resp.headers["x-events"])
    book_id = resp.json()["books"][0]["id"]
    resp = client.post(f"/api/targets/{tid}/epub/books/{book_id}/export")
    assert expected in json.loads(resp.headers["x-events"])


def test_epub_endpoints_update_library_list_stats(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1", "2", "3"])
    tid = _target_id(client)
    resp = _put_books(client, [{"chapter_start": 1}, {"chapter_start": 3}])
    assert {"topic": "targets", "type": "stats", "data": {"id": tid}} in json.loads(
        resp.headers["x-events"]
    )
    listed = next(t for t in client.get("/api/targets").json() if t["id"] == tid)
    assert (listed["chapter_count"], listed["epub_book_count"], listed["epub_pending_count"]) == (
        3,
        2,
        2,
    )

    client.post(f"/api/targets/{tid}/epub/export")
    listed = next(t for t in client.get("/api/targets").json() if t["id"] == tid)
    assert listed["epub_pending_count"] == 0


MD_URL = "https://mangadex.org/title/0aea9f43-d4a9-4bf7-bebc-550a512f9b95"


def _volume_in(path: Path) -> str | None:
    with zipfile.ZipFile(path) as zf:
        return ET.fromstring(zf.read("ComicInfo.xml")).findtext("Volume")


def test_fill_volumes_writes_mangadex_volumes_and_returns_overview(
    client: TestClient, library: Path, gallery_config: Any
) -> None:
    _write_chapters(library, ["1", "2", "3", "4"], volumes={"1": "1"})
    tid = _target_id(client)
    client.patch(f"/api/targets/{tid}", json={"metadata_source_url": MD_URL})
    gallery_config.chapter_volumes_for[MD_URL] = {
        ("Other Name", "1"): "5",
        ("Other Name", "2"): "1",
        ("Other Name", "3"): "2",
    }

    resp = client.post(f"/api/targets/{tid}/epub/volumes/fill")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_url"] == MD_URL
    assert (body["chapters"], body["missing"], body["filled"], body["unassigned"]) == (4, 3, 2, 1)
    assert body["failed"] == 0
    assert _volume_in(library / f"{SERIES} - c1.cbz") == "1"  # already set: kept
    assert _volume_in(library / f"{SERIES} - c2.cbz") == "1"
    assert _volume_in(library / f"{SERIES} - c3.cbz") == "2"
    assert _volume_in(library / f"{SERIES} - c4.cbz") is None
    overview = body["overview"]
    assert [c["volume"] for c in overview["chapters"]] == ["1", "1", "2", ""]
    assert [b["chapter_start"] for b in overview["suggested_books"]] == [1, 3, 4]
    assert {"topic": "epub", "type": "updated", "data": {"target_id": tid}} in json.loads(
        resp.headers["x-events"]
    )


def test_fill_volumes_skips_lookup_when_nothing_is_missing(
    client: TestClient, library: Path, gallery: Any
) -> None:
    _write_chapters(library, ["1", "2"], volumes={"1": "1", "2": "1"})
    tid = _target_id(client)
    client.patch(f"/api/targets/{tid}", json={"metadata_source_url": MD_URL})

    resp = client.post(f"/api/targets/{tid}/epub/volumes/fill")

    assert resp.status_code == 200, resp.text
    assert (resp.json()["missing"], resp.json()["filled"]) == (0, 0)
    assert MD_URL not in gallery.metadata_calls


def test_fill_volumes_needs_a_mangadex_url(client: TestClient, library: Path) -> None:
    _write_chapters(library, ["1"])
    resp = client.post(f"/api/targets/{_target_id(client)}/epub/volumes/fill")
    assert resp.status_code == 400
    assert "MangaDex" in resp.json()["detail"]


def test_fill_volumes_reports_a_failed_lookup(
    client: TestClient, library: Path, gallery_config: Any
) -> None:
    _write_chapters(library, ["1"])
    tid = _target_id(client)
    client.patch(f"/api/targets/{tid}", json={"metadata_source_url": MD_URL})
    gallery_config.metadata_error_for[MD_URL] = RuntimeError("HTTP 503")

    resp = client.post(f"/api/targets/{tid}/epub/volumes/fill")

    assert resp.status_code == 502
    assert "HTTP 503" in resp.json()["detail"]
    assert _volume_in(library / f"{SERIES} - c1.cbz") is None
