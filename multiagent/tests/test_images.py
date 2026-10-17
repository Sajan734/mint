import io

import pytest
from PIL import Image

from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.images import check_request_bytes, normalise_png


def enc(img, fmt="PNG", **kw):
    b = io.BytesIO()
    img.save(b, format=fmt, **kw)
    return b.getvalue()


def out(data, **kw):
    return Image.open(io.BytesIO(normalise_png(data, **kw)))


def test_large_jpeg_downscaled_longest_side_1024():
    o = out(enc(Image.new("RGB", (3000, 2000), "red"), "JPEG"))
    assert o.size == (1024, 683) and o.format == "PNG"


def test_max_side_768_supported():
    assert max(out(enc(Image.new("RGB", (2000, 1000))), max_side=768).size) == 768


def test_exif_rotated_pixels_upright():
    img = Image.new("RGB", (600, 400), "blue")
    exif = Image.Exif()
    exif[0x0112] = 6  # needs 90 degrees clockwise
    assert out(enc(img, "JPEG", exif=exif)).size == (400, 600)


def test_short_side_below_280_rejected():
    with pytest.raises(AgentError) as e:
        normalise_png(enc(Image.new("RGB", (1000, 200))))
    assert e.value.code == ErrorCode.IMAGE_INVALID


def test_decompression_bomb_rejected(monkeypatch):
    monkeypatch.setattr("buyer_agent.images.MAX_PIXELS_IN", 1000)
    with pytest.raises(AgentError):
        normalise_png(enc(Image.new("RGB", (300, 300))))


def test_gif_and_garbage_rejected():
    for data in (enc(Image.new("RGB", (400, 400)), "GIF"), b"not an image", b""):
        with pytest.raises(AgentError) as e:
            normalise_png(data)
        assert e.value.code == ErrorCode.IMAGE_INVALID


def test_output_is_png_within_jev_limits():
    o = out(enc(Image.new("RGBA", (1568, 1568), (1, 2, 3, 4))))
    assert o.mode == "RGB" and 280 <= min(o.size) and o.width * o.height <= 2_458_624


def test_request_over_32mib_rejected():
    check_request_bytes([b"x" * (16 * 1024 * 1024)] * 2)
    with pytest.raises(AgentError) as e:
        check_request_bytes([b"x" * (16 * 1024 * 1024)] * 2 + [b"x"])
    assert e.value.code == ErrorCode.PAYLOAD_TOO_LARGE
