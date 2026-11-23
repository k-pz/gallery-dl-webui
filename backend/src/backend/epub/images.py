"""Header-only image sniffing: format + pixel dimensions without decoding.

The EPUB builder copies page images byte-for-byte out of the CBZs, so it
needs each image's real media type (gallery-dl occasionally saves a JPEG
body under a `.png` name) and its dimensions (a fixed-layout page's viewport
must match the image). Parsing the few header bytes of the formats manga
sources actually serve avoids pulling in an imaging library for that.
"""

from __future__ import annotations

from dataclasses import dataclass

# Media types by lower-cased file suffix — the fallback when the bytes
# don't match a known signature.
_MEDIA_TYPE_BY_SUFFIX: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".avif": "image/avif",
}

_EXTENSION_BY_MEDIA_TYPE: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tif",
    "image/avif": "avif",
}

# JPEG start-of-frame markers carry the frame dimensions. C4 (DHT), C8 (JPG
# extension) and CC (DAC) share the 0xC_ range but are not frames.
_JPEG_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


@dataclass(frozen=True)
class ImageInfo:
    media_type: str
    extension: str
    # None when the format was recognised but its header carried no
    # dimensions we know how to read (or was truncated).
    width: int | None
    height: int | None


def media_type_for_suffix(suffix: str) -> str | None:
    return _MEDIA_TYPE_BY_SUFFIX.get(suffix.lower())


def extension_for_media_type(media_type: str) -> str:
    return _EXTENSION_BY_MEDIA_TYPE.get(media_type, "bin")


def sniff_image(data: bytes) -> ImageInfo | None:
    """Identify an image from its leading bytes. None for unknown formats."""
    if data.startswith(b"\xff\xd8"):
        return _info("image/jpeg", _jpeg_size(data))
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _info("image/png", _png_size(data))
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return _info("image/gif", _gif_size(data))
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _info("image/webp", _webp_size(data))
    if data[:2] == b"BM":
        return _info("image/bmp", _bmp_size(data))
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return _info("image/avif", _avif_size(data))
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return _info("image/tiff", None)
    return None


def _info(media_type: str, size: tuple[int, int] | None) -> ImageInfo:
    width, height = size if size is not None else (None, None)
    return ImageInfo(
        media_type=media_type,
        extension=extension_for_media_type(media_type),
        width=width,
        height=height,
    )


def _valid(width: int, height: int) -> tuple[int, int] | None:
    return (width, height) if width > 0 and height > 0 else None


def _png_size(data: bytes) -> tuple[int, int] | None:
    # Signature (8) + IHDR length (4) + "IHDR" (4), then width/height (4+4, BE).
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return _valid(int.from_bytes(data[16:20]), int.from_bytes(data[20:24]))


def _gif_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10:
        return None
    return _valid(int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little"))


def _bmp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 26:
        return None
    width = int.from_bytes(data[18:22], "little", signed=True)
    # Negative height means a top-down bitmap; the magnitude is the size.
    height = abs(int.from_bytes(data[22:26], "little", signed=True))
    return _valid(width, height)


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    n = len(data)
    while i < n:
        if data[i] != 0xFF:
            return None
        # Any number of 0xFF fill bytes may precede a marker.
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            return None
        marker = data[i]
        i += 1
        # Standalone markers (no length field): TEM, RST0-7, SOI, EOI.
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:
            continue
        if i + 2 > n:
            return None
        length = int.from_bytes(data[i : i + 2])
        if marker in _JPEG_SOF_MARKERS:
            # Length (2), precision (1), height (2), width (2).
            if i + 7 > n:
                return None
            height = int.from_bytes(data[i + 3 : i + 5])
            width = int.from_bytes(data[i + 5 : i + 7])
            return _valid(width, height)
        if length < 2:
            return None
        i += length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8 ":
        # Lossy: frame tag (3) + start code 9d 01 2a (3) at offset 20, then
        # 14-bit width/height (the top two bits are a scaling hint).
        if len(data) < 30 or data[23:26] != b"\x9d\x01\x2a":
            return None
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return _valid(width, height)
    if chunk == b"VP8L":
        # Lossless: signature byte 0x2f, then (width-1) and (height-1) packed
        # as two 14-bit little-endian fields.
        if len(data) < 25 or data[20] != 0x2F:
            return None
        bits = int.from_bytes(data[21:25], "little")
        return _valid((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if chunk == b"VP8X":
        # Extended: flags (4) at 20, then 24-bit (canvas width-1) and
        # (canvas height-1).
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return _valid(width, height)
    return None


def _avif_size(data: bytes) -> tuple[int, int] | None:
    # The `ispe` (image spatial extents) property box: size (4) + "ispe" (4)
    # + version/flags (4) + width (4, BE) + height (4, BE). It lives inside
    # the `meta` box near the start of the file; a byte search is enough for
    # a viewport hint.
    idx = data.find(b"ispe")
    if idx < 4 or idx + 16 > len(data):
        return None
    width = int.from_bytes(data[idx + 8 : idx + 12])
    height = int.from_bytes(data[idx + 12 : idx + 16])
    return _valid(width, height)
