import pytest

from backend.epub.images import ImageInfo, media_type_for_suffix, sniff_image
from tests._helpers import jpeg_bytes, png_bytes


def _riff_webp(chunk: bytes, payload: bytes) -> bytes:
    body = b"WEBP" + chunk + len(payload).to_bytes(4, "little") + payload
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def test_png_dimensions() -> None:
    assert sniff_image(png_bytes(800, 1200)) == ImageInfo("image/png", "png", 800, 1200)


def test_jpeg_dimensions_skip_app_segments() -> None:
    assert sniff_image(jpeg_bytes(1024, 1536)) == ImageInfo("image/jpeg", "jpg", 1024, 1536)


def test_jpeg_tolerates_fill_bytes_before_marker() -> None:
    data = jpeg_bytes(640, 960)
    # Insert extra 0xFF fill bytes ahead of the APP0 marker.
    padded = data[:2] + b"\xff\xff" + data[2:]
    info = sniff_image(padded)
    assert info is not None
    assert (info.width, info.height) == (640, 960)


def test_truncated_jpeg_keeps_type_without_size() -> None:
    info = sniff_image(b"\xff\xd8\xff\xe0\x00")
    assert info == ImageInfo("image/jpeg", "jpg", None, None)


def test_gif_dimensions() -> None:
    data = b"GIF89a" + (320).to_bytes(2, "little") + (240).to_bytes(2, "little") + b"\x00" * 4
    assert sniff_image(data) == ImageInfo("image/gif", "gif", 320, 240)


def test_webp_lossy_dimensions() -> None:
    payload = b"\x00\x00\x00" + b"\x9d\x01\x2a" + (700).to_bytes(2, "little")
    payload += (1000).to_bytes(2, "little")
    assert sniff_image(_riff_webp(b"VP8 ", payload)) == ImageInfo("image/webp", "webp", 700, 1000)


def test_webp_lossless_dimensions() -> None:
    bits = (500 - 1) | ((900 - 1) << 14)
    payload = b"\x2f" + bits.to_bytes(4, "little")
    assert sniff_image(_riff_webp(b"VP8L", payload)) == ImageInfo("image/webp", "webp", 500, 900)


def test_webp_extended_dimensions() -> None:
    payload = b"\x00" * 4 + (1200 - 1).to_bytes(3, "little") + (1800 - 1).to_bytes(3, "little")
    assert sniff_image(_riff_webp(b"VP8X", payload)) == ImageInfo("image/webp", "webp", 1200, 1800)


def test_bmp_top_down_height_is_positive() -> None:
    header = b"BM" + b"\x00" * 16 + (400).to_bytes(4, "little", signed=True)
    header += (-600).to_bytes(4, "little", signed=True)
    assert sniff_image(header) == ImageInfo("image/bmp", "bmp", 400, 600)


def test_avif_dimensions_from_ispe_box() -> None:
    data = b"\x00\x00\x00\x1cftypavif" + b"\x00" * 16
    data += (20).to_bytes(4) + b"ispe" + b"\x00" * 4 + (900).to_bytes(4) + (1300).to_bytes(4)
    assert sniff_image(data) == ImageInfo("image/avif", "avif", 900, 1300)


def test_png_bytes_with_wrong_suffix_are_still_png() -> None:
    # The sniffer only looks at content; the suffix is irrelevant.
    assert sniff_image(png_bytes(10, 20)) is not None


def test_unknown_bytes_return_none() -> None:
    assert sniff_image(b"not an image at all") is None


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [(".JPG", "image/jpeg"), (".png", "image/png"), (".webp", "image/webp"), (".txt", None)],
)
def test_media_type_for_suffix(suffix: str, expected: str | None) -> None:
    assert media_type_for_suffix(suffix) == expected
