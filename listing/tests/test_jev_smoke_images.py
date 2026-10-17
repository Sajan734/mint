"""Image prep in the smoke script. Plain generated images only check sizes; no Jev calls."""

import io

import pytest
from PIL import Image as PILImage

from scripts.jev_smoke import EXIF_ORIENTATION, FIT, ImageProblem, load_image


def write(tmp_path, size, fmt="JPEG", orientation=None):
    img = PILImage.new("RGB", size, (120, 120, 120))
    path = tmp_path / f"img.{fmt.lower()}"
    kwargs = {}
    if orientation is not None:
        exif = PILImage.Exif()
        exif[EXIF_ORIENTATION] = orientation
        kwargs["exif"] = exif
    img.save(path, format=fmt, **kwargs)
    return path


def size_of(data):
    with PILImage.open(io.BytesIO(data)) as img:
        return img.size


def test_phone_photo_rejected_without_fit(tmp_path):
    with pytest.raises(ImageProblem, match="try --fit"):
        load_image(write(tmp_path, (4032, 3024)))


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_fit_shrinks_long_side(tmp_path, fmt):
    data, info = load_image(write(tmp_path, (4032, 3024), fmt), fit=True)
    assert size_of(data) == (FIT["long_side_px"], 768)
    assert "shrunk from 4032x3024" in info


def test_fit_never_enlarges(tmp_path):
    path = write(tmp_path, (800, 600))
    data, info = load_image(path, fit=True)
    assert data == path.read_bytes()
    assert "shrunk" not in info


def test_fit_after_exif_rotation(tmp_path):
    data, info = load_image(write(tmp_path, (4032, 3024), orientation=6), fit=True)
    assert size_of(data) == (768, FIT["long_side_px"])
    assert "rotated upright" in info and "shrunk from 3024x4032" in info


def test_fit_still_rejects_too_narrow(tmp_path):
    with pytest.raises(ImageProblem, match="each side must be"):
        load_image(write(tmp_path, (4000, 300)), fit=True)  # 1024x77 after shrinking
