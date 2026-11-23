import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.epub.builder import (
    DEFAULT_PAGE_SIZE,
    EpubChapter,
    EpubMetadata,
    build_epub,
)
from tests._helpers import jpeg_bytes, png_bytes, write_chapter_cbz

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}


def _meta(**overrides: object) -> EpubMetadata:
    base: dict[str, object] = {
        "identifier": "urn:uuid:00000000-0000-0000-0000-000000000001",
        "title": "Series, Vol. 2",
        "series": "Series",
        "series_index": 2,
        "language": "en",
        "authors": ("Writer Name", "Artist Name"),
        "publisher": "Pub & Co",
        "description": "A <great> story.",
        "published": "2020-03-04",
        "tags": ("Action", "Drama"),
        "source_url": "https://example/series",
        "reading_direction": "ltr",
    }
    base.update(overrides)
    return EpubMetadata(**base)  # type: ignore[arg-type]


def _chapters(tmp_path: Path) -> list[EpubChapter]:
    c1 = write_chapter_cbz(
        tmp_path / "S - c001.cbz",
        "Series",
        "1",
        pages=[
            ("010.png", png_bytes(800, 1200)),
            ("002.png", png_bytes(800, 1200)),
            ("001.jpg", jpeg_bytes(1600, 1200)),
        ],
    )
    c2 = write_chapter_cbz(
        tmp_path / "S - c002.cbz", "Series", "2", pages=[("001.png", png_bytes(700, 1000))]
    )
    return [
        EpubChapter(number="1", title="Start", cbz_path=c1),
        EpubChapter(number="2", title="", cbz_path=c2),
    ]


def _build(tmp_path: Path, **meta_overrides: object) -> Path:
    dest = tmp_path / "out" / "book.epub"
    build_epub(
        dest,
        _meta(**meta_overrides),
        _chapters(tmp_path),
        modified=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    return dest


def _opf(zf: zipfile.ZipFile) -> ET.Element:
    return ET.fromstring(zf.read("OEBPS/content.opf"))


def test_ocf_container_layout(tmp_path: Path) -> None:
    dest = _build(tmp_path)
    with zipfile.ZipFile(dest) as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert first.extra == b""
        assert zf.read("mimetype") == b"application/epub+zip"
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
        assert rootfile is not None
        assert rootfile.get("full-path") == "OEBPS/content.opf"
        # Every XML document in the book must be well-formed.
        for name in zf.namelist():
            if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                ET.fromstring(zf.read(name))
    assert not dest.with_name(dest.name + ".part").exists()


def test_result_counts(tmp_path: Path) -> None:
    result = build_epub(tmp_path / "b.epub", _meta(), _chapters(tmp_path))
    assert (result.chapters, result.pages) == (2, 4)


def test_images_are_copied_byte_for_byte_in_natural_order(tmp_path: Path) -> None:
    dest = _build(tmp_path)
    with zipfile.ZipFile(dest) as zf:
        # "001.jpg" < "002.png" < "010.png"; the JPEG keeps its own extension.
        assert zf.read("OEBPS/images/c0001-p0001.jpg") == jpeg_bytes(1600, 1200)
        assert zf.read("OEBPS/images/c0001-p0002.png") == png_bytes(800, 1200)
        assert zf.read("OEBPS/images/c0001-p0003.png") == png_bytes(800, 1200)
        assert zf.read("OEBPS/images/c0002-p0001.png") == png_bytes(700, 1000)
        assert zf.getinfo("OEBPS/images/c0001-p0001.jpg").compress_type == zipfile.ZIP_STORED


def test_page_viewport_matches_image(tmp_path: Path) -> None:
    dest = _build(tmp_path)
    with zipfile.ZipFile(dest) as zf:
        page = zf.read("OEBPS/pages/c0001-p0001.xhtml").decode()
        assert '<meta name="viewport" content="width=1600, height=1200"/>' in page
        assert 'src="../images/c0001-p0001.jpg"' in page
        page2 = zf.read("OEBPS/pages/c0002-p0001.xhtml").decode()
        assert 'content="width=700, height=1000"' in page2


def test_opf_metadata_for_calibre_and_epub3(tmp_path: Path) -> None:
    dest = _build(tmp_path)
    with zipfile.ZipFile(dest) as zf:
        opf = _opf(zf)
    md = opf.find("opf:metadata", NS)
    assert md is not None
    assert opf.get("version") == "3.0"
    assert opf.get("unique-identifier") == "book-id"
    assert md.findtext("dc:identifier", namespaces=NS) == (
        "urn:uuid:00000000-0000-0000-0000-000000000001"
    )
    assert md.findtext("dc:title", namespaces=NS) == "Series, Vol. 2"
    assert md.findtext("dc:language", namespaces=NS) == "en"
    assert [c.text for c in md.findall("dc:creator", NS)] == ["Writer Name", "Artist Name"]
    roles = {
        m.get("refines"): m.text for m in md.findall("opf:meta", NS) if m.get("property") == "role"
    }
    assert roles == {"#creator-1": "aut", "#creator-2": "aut"}
    assert md.findtext("dc:publisher", namespaces=NS) == "Pub & Co"
    assert md.findtext("dc:date", namespaces=NS) == "2020-03-04"
    assert md.findtext("dc:description", namespaces=NS) == "A <great> story."
    assert [s.text for s in md.findall("dc:subject", NS)] == ["Action", "Drama"]
    assert md.findtext("dc:source", namespaces=NS) == "https://example/series"

    props = {m.get("property"): m.text for m in md.findall("opf:meta", NS) if m.get("property")}
    assert props["dcterms:modified"] == "2026-01-02T03:04:05Z"
    assert props["belongs-to-collection"] == "Series"
    assert props["collection-type"] == "series"
    assert props["group-position"] == "2"
    assert props["rendition:layout"] == "pre-paginated"
    assert props["rendition:spread"] == "landscape"

    named = {m.get("name"): m.get("content") for m in md.findall("opf:meta", NS) if m.get("name")}
    assert named["calibre:series"] == "Series"
    assert named["calibre:series_index"] == "2"
    assert named["cover"] == "img-c0001-p0001"


def test_manifest_spine_and_cover(tmp_path: Path) -> None:
    dest = _build(tmp_path)
    with zipfile.ZipFile(dest) as zf:
        opf = _opf(zf)
        names = set(zf.namelist())
    items = {i.get("id"): i for i in opf.findall("opf:manifest/opf:item", NS)}
    assert items["nav"].get("properties") == "nav"
    assert items["img-c0001-p0001"].get("properties") == "cover-image"
    assert items["img-c0001-p0001"].get("media-type") == "image/jpeg"
    assert items["img-c0001-p0002"].get("media-type") == "image/png"
    for item in items.values():
        assert f"OEBPS/{item.get('href')}" in names
    spine = opf.find("opf:spine", NS)
    assert spine is not None
    assert spine.get("page-progression-direction") == "ltr"
    assert [r.get("idref") for r in spine.findall("opf:itemref", NS)] == [
        "page-c0001-p0001",
        "page-c0001-p0002",
        "page-c0001-p0003",
        "page-c0002-p0001",
    ]


def test_rtl_reading_direction_sets_page_progression(tmp_path: Path) -> None:
    dest = _build(tmp_path, reading_direction="rtl")
    with zipfile.ZipFile(dest) as zf:
        spine = _opf(zf).find("opf:spine", NS)
    assert spine is not None
    assert spine.get("page-progression-direction") == "rtl"


def test_webtoon_disables_spreads(tmp_path: Path) -> None:
    dest = _build(tmp_path, reading_direction="webtoon")
    with zipfile.ZipFile(dest) as zf:
        md = _opf(zf).find("opf:metadata", NS)
    assert md is not None
    spread = [m.text for m in md.findall("opf:meta", NS) if m.get("property") == "rendition:spread"]
    assert spread == ["none"]


def test_toc_has_one_entry_per_chapter(tmp_path: Path) -> None:
    dest = _build(tmp_path)
    with zipfile.ZipFile(dest) as zf:
        nav = ET.fromstring(zf.read("OEBPS/nav.xhtml"))
        ncx = ET.fromstring(zf.read("OEBPS/toc.ncx"))
    toc = nav.find(".//xhtml:nav[@id='toc']", NS)
    assert toc is not None
    links = [(a.text, a.get("href")) for a in toc.findall(".//xhtml:a", NS)]
    assert links == [
        ("Chapter 1: Start", "pages/c0001-p0001.xhtml"),
        ("Chapter 2", "pages/c0002-p0001.xhtml"),
    ]
    labels = [t.text for t in ncx.findall(".//ncx:navPoint/ncx:navLabel/ncx:text", NS)]
    assert labels == ["Chapter 1: Start", "Chapter 2"]


def test_optional_metadata_is_omitted_when_blank(tmp_path: Path) -> None:
    dest = _build(
        tmp_path, authors=(), publisher="", description="", published="", tags=(), source_url=""
    )
    with zipfile.ZipFile(dest) as zf:
        md = _opf(zf).find("opf:metadata", NS)
    assert md is not None
    for tag in ("creator", "publisher", "date", "description", "subject", "source"):
        assert md.find(f"dc:{tag}", NS) is None


def test_control_characters_are_stripped_from_text(tmp_path: Path) -> None:
    dest = _build(tmp_path, description="bad\x0bchar")
    with zipfile.ZipFile(dest) as zf:
        md = _opf(zf).find("opf:metadata", NS)
    assert md is not None
    assert md.findtext("dc:description", namespaces=NS) == "badchar"


def test_unknown_image_dimensions_fall_back(tmp_path: Path) -> None:
    cbz = write_chapter_cbz(tmp_path / "c.cbz", "S", "1", pages=[("001.jpg", b"garbage")])
    dest = tmp_path / "b.epub"
    build_epub(dest, _meta(), [EpubChapter("1", "", cbz)])
    width, height = DEFAULT_PAGE_SIZE
    with zipfile.ZipFile(dest) as zf:
        page = zf.read("OEBPS/pages/c0001-p0001.xhtml").decode()
        assert f'content="width={width}, height={height}"' in page
        # Unknown bytes keep the media type implied by the member's suffix.
        assert "OEBPS/images/c0001-p0001.jpg" in zf.namelist()


def test_chapter_without_pages_fails_and_leaves_no_files(tmp_path: Path) -> None:
    cbz = tmp_path / "empty.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("ComicInfo.xml", "<ComicInfo/>")
    dest = tmp_path / "b.epub"
    with pytest.raises(ValueError, match="no page images"):
        build_epub(dest, _meta(), [EpubChapter("1", "", cbz)])
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def test_no_chapters_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one chapter"):
        build_epub(tmp_path / "b.epub", _meta(), [])


def test_rebuild_replaces_existing_file(tmp_path: Path) -> None:
    dest = _build(tmp_path)
    build_epub(dest, _meta(title="Renamed"), _chapters(tmp_path))
    with zipfile.ZipFile(dest) as zf:
        md = _opf(zf).find("opf:metadata", NS)
    assert md is not None
    assert md.findtext("dc:title", namespaces=NS) == "Renamed"
