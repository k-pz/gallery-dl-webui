"""Build a fixed-layout EPUB3 book from packed chapter CBZs.

One book bundles any number of chapters. Every page image is copied
byte-for-byte out of its CBZ (no re-encoding) and gets its own pre-paginated
XHTML page whose viewport matches the image, so readers scale each page to
the screen like a comic reader would.

Metadata is written for two audiences at once:

- EPUB3 readers: `belongs-to-collection` (series + `group-position`),
  `dc:creator` with MARC relator roles, `rendition:*` fixed-layout hints,
  `page-progression-direction` for right-to-left manga, a `nav` TOC with
  one entry per chapter.
- Calibre: the legacy `calibre:series` / `calibre:series_index` metas and an
  OPF2 `cover` meta, plus a `toc.ncx` for EPUB2-era readers.

The builder is pure I/O over the paths it is given — no app state — so the
router can run it on a worker thread.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from backend.comic_metadata import IMAGE_SUFFIXES
from backend.epub.images import extension_for_media_type, media_type_for_suffix, sniff_image

# Viewport for a page whose image dimensions couldn't be read and no earlier
# page in the book supplied any (a typical manga page aspect ratio).
DEFAULT_PAGE_SIZE = (1000, 1500)

_CONTAINER_XML = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_STYLE_CSS = """@page { margin: 0; }
html, body { margin: 0; padding: 0; width: 100%; height: 100%; }
body { display: block; overflow: hidden; }
img { display: block; width: 100%; height: 100%; margin: 0; padding: 0; object-fit: contain; }
"""

# XML 1.0 forbids most C0 control characters; scraped descriptions do
# occasionally carry them.
_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_NATURAL_SPLIT = re.compile(r"(\d+)")


@dataclass(frozen=True)
class EpubChapter:
    # Display chapter number (ComicInfo `Number`, e.g. "12" or "12.5").
    number: str
    title: str
    cbz_path: Path


@dataclass(frozen=True)
class EpubMetadata:
    # Full unique identifier, e.g. "urn:uuid:…". Kept stable across
    # re-exports so readers treat a re-export as the same book.
    identifier: str
    title: str
    series: str
    series_index: int
    language: str = "und"
    authors: tuple[str, ...] = ()
    publisher: str = ""
    description: str = ""
    # `YYYY-MM-DD` or `YYYY`; empty to omit.
    published: str = ""
    tags: tuple[str, ...] = ()
    source_url: str = ""
    reading_direction: str = "ltr"


@dataclass(frozen=True)
class EpubBuildResult:
    chapters: int
    pages: int


@dataclass(frozen=True)
class _ManifestItem:
    id: str
    href: str
    media_type: str
    properties: str = ""


def build_epub(
    dest: Path,
    meta: EpubMetadata,
    chapters: Sequence[EpubChapter],
    *,
    modified: datetime | None = None,
) -> EpubBuildResult:
    """Write the book to `dest` atomically (via a `.part` sibling).

    Raises ValueError when there are no chapters or a chapter archive holds
    no page images — a silently incomplete book is worse than a failed
    export the user can see.
    """
    if not chapters:
        raise ValueError("a book needs at least one chapter")
    modified_at = (modified or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    if part.exists():
        part.unlink()

    manifest: list[_ManifestItem] = []
    spine: list[str] = []
    toc: list[tuple[str, str]] = []  # (label, href of the chapter's first page)
    last_size = DEFAULT_PAGE_SIZE
    total_pages = 0

    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as out:
            # The OCF spec requires `mimetype` first, stored, with no extra
            # field — readers sniff the container from those leading bytes.
            out.writestr(
                zipfile.ZipInfo("mimetype"),
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            out.writestr("META-INF/container.xml", _CONTAINER_XML)

            for ci, chapter in enumerate(chapters, start=1):
                with zipfile.ZipFile(chapter.cbz_path) as cbz:
                    names = _page_entries(cbz)
                    if not names:
                        raise ValueError(f"no page images in {chapter.cbz_path.name}")
                    for pi, name in enumerate(names, start=1):
                        data = cbz.read(name)
                        info = sniff_image(data)
                        if info is not None:
                            media_type, ext = info.media_type, info.extension
                            if info.width is not None and info.height is not None:
                                last_size = (info.width, info.height)
                        else:
                            media_type = media_type_for_suffix(Path(name).suffix) or "image/jpeg"
                            ext = extension_for_media_type(media_type)
                        stem = f"c{ci:04d}-p{pi:04d}"
                        img_href = f"images/{stem}.{ext}"
                        page_href = f"pages/{stem}.xhtml"
                        # Images are already compressed; deflating them again
                        # burns CPU for ~0% gain.
                        out.writestr(f"OEBPS/{img_href}", data, compress_type=zipfile.ZIP_STORED)
                        out.writestr(
                            f"OEBPS/{page_href}",
                            _page_xhtml(
                                img_href=f"../{img_href}",
                                size=last_size,
                                title=f"{_chapter_label(chapter)} — {pi}",
                                language=meta.language,
                            ),
                        )
                        is_cover = ci == 1 and pi == 1
                        manifest.append(
                            _ManifestItem(
                                id=f"img-{stem}",
                                href=img_href,
                                media_type=media_type,
                                properties="cover-image" if is_cover else "",
                            )
                        )
                        manifest.append(
                            _ManifestItem(
                                id=f"page-{stem}",
                                href=page_href,
                                media_type="application/xhtml+xml",
                            )
                        )
                        spine.append(f"page-{stem}")
                        if pi == 1:
                            toc.append((_chapter_label(chapter), page_href))
                        total_pages += 1

            out.writestr("OEBPS/style.css", _STYLE_CSS)
            out.writestr("OEBPS/nav.xhtml", _nav_xhtml(meta, toc))
            out.writestr("OEBPS/toc.ncx", _toc_ncx(meta, toc))
            out.writestr("OEBPS/content.opf", _content_opf(meta, manifest, spine, modified_at))
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return EpubBuildResult(chapters=len(chapters), pages=total_pages)


def _page_entries(cbz: zipfile.ZipFile) -> list[str]:
    """Image members of a CBZ in reading order (natural sort on the name)."""
    names = [
        info.filename
        for info in cbz.infolist()
        if not info.is_dir() and Path(info.filename).suffix.lower() in IMAGE_SUFFIXES
    ]
    return sorted(names, key=_natural_key)


def _natural_key(name: str) -> list[int | str]:
    # re.split with a capture group alternates text/digit runs, so the
    # str/int positions line up between any two keys.
    return [int(tok) if tok.isdigit() else tok.lower() for tok in _NATURAL_SPLIT.split(name)]


def chapter_label(number: str, title: str) -> str:
    label = f"Chapter {number}" if number else "Chapter"
    return f"{label}: {title}" if title else label


def _chapter_label(chapter: EpubChapter) -> str:
    return chapter_label(chapter.number, chapter.title)


def _x(value: str) -> str:
    """Escape text for an XML text node or a double-quoted attribute."""
    return escape(_XML_INVALID.sub("", value), {'"': "&quot;"})


def _page_xhtml(*, img_href: str, size: tuple[int, int], title: str, language: str) -> str:
    width, height = size
    lang = _x(language)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        f'<meta name="viewport" content="width={width}, height={height}"/>\n'
        f"<title>{_x(title)}</title>\n"
        '<link rel="stylesheet" type="text/css" href="../style.css"/>\n'
        "</head>\n"
        f'<body><img src="{_x(img_href)}" alt=""/></body>\n'
        "</html>\n"
    )


def _nav_xhtml(meta: EpubMetadata, toc: list[tuple[str, str]]) -> str:
    lang = _x(meta.language)
    items = "\n".join(f'<li><a href="{_x(href)}">{_x(label)}</a></li>' for label, href in toc)
    first = _x(toc[0][1])
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">\n'
        f'<head><meta charset="utf-8"/><title>{_x(meta.title)}</title></head>\n'
        "<body>\n"
        f'<nav epub:type="toc" id="toc"><h1>{_x(meta.title)}</h1>\n<ol>\n{items}\n</ol></nav>\n'
        '<nav epub:type="landmarks" id="landmarks" hidden="hidden"><ol>\n'
        f'<li><a epub:type="cover" href="{first}">Cover</a></li>\n'
        f'<li><a epub:type="bodymatter" href="{first}">Start</a></li>\n'
        "</ol></nav>\n"
        "</body>\n"
        "</html>\n"
    )


def _toc_ncx(meta: EpubMetadata, toc: list[tuple[str, str]]) -> str:
    points = "\n".join(
        f'<navPoint id="nav-{i}" playOrder="{i}"><navLabel><text>{_x(label)}</text></navLabel>'
        f'<content src="{_x(href)}"/></navPoint>'
        for i, (label, href) in enumerate(toc, start=1)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" '
        f'xml:lang="{_x(meta.language)}">\n'
        "<head>\n"
        f'<meta name="dtb:uid" content="{_x(meta.identifier)}"/>\n'
        '<meta name="dtb:depth" content="1"/>\n'
        '<meta name="dtb:totalPageCount" content="0"/>\n'
        '<meta name="dtb:maxPageNumber" content="0"/>\n'
        "</head>\n"
        f"<docTitle><text>{_x(meta.title)}</text></docTitle>\n"
        f"<navMap>\n{points}\n</navMap>\n"
        "</ncx>\n"
    )


def _content_opf(
    meta: EpubMetadata,
    manifest: list[_ManifestItem],
    spine: list[str],
    modified: datetime,
) -> str:
    lines: list[str] = [
        f'<dc:identifier id="book-id">{_x(meta.identifier)}</dc:identifier>',
        f'<dc:title id="title">{_x(meta.title)}</dc:title>',
        f"<dc:language>{_x(meta.language)}</dc:language>",
    ]
    for i, author in enumerate(meta.authors, start=1):
        lines.append(f'<dc:creator id="creator-{i}">{_x(author)}</dc:creator>')
        lines.append(
            f'<meta refines="#creator-{i}" property="role" scheme="marc:relators">aut</meta>'
        )
    if meta.publisher:
        lines.append(f"<dc:publisher>{_x(meta.publisher)}</dc:publisher>")
    if meta.published:
        lines.append(f"<dc:date>{_x(meta.published)}</dc:date>")
    if meta.description:
        lines.append(f"<dc:description>{_x(meta.description)}</dc:description>")
    lines.extend(f"<dc:subject>{_x(tag)}</dc:subject>" for tag in meta.tags)
    if meta.source_url:
        lines.append(f"<dc:source>{_x(meta.source_url)}</dc:source>")
    lines.append(
        f'<meta property="dcterms:modified">{modified.strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>'
    )
    if meta.series:
        lines += [
            f'<meta property="belongs-to-collection" id="series">{_x(meta.series)}</meta>',
            '<meta refines="#series" property="collection-type">series</meta>',
            f'<meta refines="#series" property="group-position">{meta.series_index}</meta>',
            f'<meta name="calibre:series" content="{_x(meta.series)}"/>',
            f'<meta name="calibre:series_index" content="{meta.series_index}"/>',
        ]
    cover = next((item for item in manifest if item.properties == "cover-image"), None)
    if cover is not None:
        lines.append(f'<meta name="cover" content="{cover.id}"/>')
    # Two-page spreads only make sense for paged reading; strips are read one
    # image at a time.
    spread = "none" if meta.reading_direction in ("vertical", "webtoon") else "landscape"
    lines += [
        '<meta property="rendition:layout">pre-paginated</meta>',
        '<meta property="rendition:orientation">auto</meta>',
        f'<meta property="rendition:spread">{spread}</meta>',
    ]

    items = [
        _ManifestItem("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
        _ManifestItem("ncx", "toc.ncx", "application/x-dtbncx+xml"),
        _ManifestItem("css", "style.css", "text/css"),
        *manifest,
    ]
    manifest_xml = "\n    ".join(
        f'<item id="{item.id}" href="{_x(item.href)}" media-type="{item.media_type}"'
        + (f' properties="{item.properties}"' if item.properties else "")
        + "/>"
        for item in items
    )
    spine_xml = "\n    ".join(f'<itemref idref="{idref}"/>' for idref in spine)
    direction = "rtl" if meta.reading_direction == "rtl" else "ltr"
    metadata_xml = "\n    ".join(lines)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="book-id" xml:lang="{_x(meta.language)}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">\n'
        f"    {metadata_xml}\n"
        "  </metadata>\n"
        f"  <manifest>\n    {manifest_xml}\n  </manifest>\n"
        f'  <spine toc="ncx" page-progression-direction="{direction}">\n'
        f"    {spine_xml}\n"
        "  </spine>\n"
        "</package>\n"
    )
