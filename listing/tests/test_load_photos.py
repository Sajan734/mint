"""load_photos: the item folder's photos -> upright, right-sized JPEG views, in name order (no network)."""

import asyncio
import io

import pytest
from PIL import Image as PILImage

from contracts import RunContext
from stages.load_photos import PHOTOS, PhotoError, load_photos, load_views, prepare

EXIF_ORIENTATION = 274


def jpeg(size, colour=(120, 60, 30), orientation=None):
    img = PILImage.new("RGB", size, colour)
    buf = io.BytesIO()
    if orientation:
        exif = img.getexif()
        exif[EXIF_ORIENTATION] = orientation
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def size_of(data):
    with PILImage.open(io.BytesIO(data)) as img:
        return img.size, img.format


def test_a_phone_photo_is_shrunk_to_the_working_size():
    assert size_of(prepare(jpeg((4032, 3024)))) == ((1024, 768), "JPEG")


def test_exif_rotation_is_applied_to_the_pixels():
    assert size_of(prepare(jpeg((800, 600), orientation=6)))[0] == (600, 800)  # rotated 90 degrees: portrait


def test_small_photos_are_kept_and_tiny_ones_refused():
    assert size_of(prepare(jpeg((640, 480))))[0] == (640, 480)
    with pytest.raises(PhotoError, match="each side needs"):
        prepare(jpeg((200, 150)))


def item_with(tmp_path, names):
    photos = tmp_path / "item" / "photos"
    photos.mkdir(parents=True)
    for name in names:
        (photos / name).write_bytes(jpeg((1200, 900)))
    return tmp_path / "item"


def test_views_follow_file_name_order_with_their_urls(tmp_path):
    item = item_with(tmp_path, ["b.jpg", "a.JPG", "c.png.txt", "c.jpeg"])
    urls = ["https://x.test/a.jpg", "http://not-https/b.jpg"]
    views = load_views(item, "item", tmp_path / "views", urls)
    assert [v.view_id for v in views.views] == ["p01", "p02", "p03"]  # a.JPG, b.jpg, c.jpeg (the .txt is skipped)
    assert [v.label for v in views.views] == ["photo 1", "photo 2", "photo 3"]
    assert [v.source_url for v in views.views] == ["https://x.test/a.jpg", None, None]  # only https URLs count
    assert size_of((tmp_path / "views" / "p01.jpg").read_bytes())[0] == (1024, 768)


def test_no_photos_is_a_clear_error(tmp_path):
    (tmp_path / "item").mkdir()
    with pytest.raises(PhotoError, match="no photos in"):
        load_views(tmp_path / "item", "item", tmp_path / "views")


def test_at_most_max_photos_are_used(tmp_path, monkeypatch):
    monkeypatch.setitem(PHOTOS, "max_photos", 2)
    views = load_views(item_with(tmp_path, ["1.jpg", "2.jpg", "3.jpg"]), "item", tmp_path / "views")
    assert len(views.views) == 2


def test_stage_writes_views_into_the_run_folder(tmp_path):
    item = item_with(tmp_path, [f"{i}.jpg" for i in range(8)])
    ctx = RunContext(item_id="item", item_dir=item, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    views = asyncio.run(load_photos(ctx, None, [["0.jpg", 1]]))
    assert len(views.views) == 8 and (tmp_path / "runs" / "views" / "p08.jpg").is_file()
