"""fit_for_jev on generated images (only sizes and formats are checked)."""

import io

import pytest
from PIL import Image as PILImage

from images import EXIF_ORIENTATION, JEV_LIMITS, ImageProblem, fit_for_jev


def encode(size, fmt="JPEG", orientation=None):
    buf = io.BytesIO()
    kwargs = {}
    if orientation is not None:
        exif = PILImage.Exif()
        exif[EXIF_ORIENTATION] = orientation
        kwargs["exif"] = exif
    PILImage.new("RGB", size, (240, 240, 240)).save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def size_of(data):
    with PILImage.open(io.BytesIO(data)) as img:
        return img.size, img.format


def test_in_range_image_is_unchanged():
    data = encode((1000, 800))
    fitted = fit_for_jev(data)
    assert fitted.data == data and fitted.notes == [] and fitted.mime == "image/jpeg"


def test_large_image_is_shrunk():
    fitted = fit_for_jev(encode((4000, 3000), "PNG"))
    assert size_of(fitted.data) == ((1568, 1176), "PNG")
    assert fitted.notes == ["shrunk from 4000x3000"]


def test_webp_is_converted_to_jpeg():
    fitted = fit_for_jev(encode((800, 800), "WEBP"))
    assert fitted.mime == "image/jpeg" and size_of(fitted.data)[1] == "JPEG"
    assert "converted from WEBP" in fitted.notes


def test_exif_rotation_applied():
    fitted = fit_for_jev(encode((1200, 800), orientation=6))
    assert (fitted.width, fitted.height) == (800, 1200)


@pytest.mark.parametrize("size", [(200, 900), (2000, 300)])  # second one is 1568x235 after shrinking
def test_too_narrow_is_rejected(size):
    with pytest.raises(ImageProblem, match=str(JEV_LIMITS["min_side_px"])):
        fit_for_jev(encode(size))


def test_garbage_is_rejected():
    with pytest.raises(ImageProblem, match="not a readable image"):
        fit_for_jev(b"<html>not an image</html>")
