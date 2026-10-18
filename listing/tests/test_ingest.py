"""ingest.py: a finished scan's 8 views become an item folder the pipeline runs on (no network)."""

import json

import pytest

from ingest import IngestError, ingest, public_url, view_urls

BASE, SCAN = "https://example.test", "11111111-2222-3333-4444-555555555555"


def manifest_with(names):
    folder = public_url(f"views/{SCAN}", BASE)
    return {"scan_id": SCAN, "views": {"layout": "cube_top", "items": [
        {"name": n, "grey_url": f"{folder}/{n}_grey.png", "transparent_url": f"{folder}/{n}.png"} for n in names]}}


def serve(manifest):
    served = {public_url(f"splats/{SCAN}.json", BASE): json.dumps(manifest).encode()}
    for v in manifest["views"]["items"]:
        served[v["grey_url"]] = f"png {v['name']}".encode()
    return served


NAMES = [f"{i:02d}_az{i * 45:03d}_el+45" for i in range(8)]


def test_ingest_writes_the_views_as_photos(tmp_path):
    manifest = manifest_with(NAMES)
    served, requested = serve(manifest), []

    def fake_get(url):
        requested.append(url)
        return served[url]

    item = ingest(SCAN, "Logitech M185", root=tmp_path, base=BASE, get=fake_get)
    assert item == tmp_path / SCAN and sorted(requested) == sorted(served)  # the grey views only, no splat
    photos = sorted(p.name for p in (item / "photos").iterdir())
    assert photos == [f"{n}_grey.png" for n in NAMES]
    inputs = json.loads((item / "input.json").read_text())
    assert inputs["seller_name"] == "Logitech M185"
    assert inputs["photo_urls"] == [v["grey_url"] for v in manifest["views"]["items"]]  # same order as the photos
    assert json.loads((item / "manifest.json").read_text())["scan_id"] == SCAN
    assert not (tmp_path / f".{SCAN}.partial").exists()


def test_a_manifest_without_views_is_an_error_and_writes_nothing(tmp_path):
    served = {public_url(f"splats/{SCAN}.json", BASE): json.dumps({"scan_id": SCAN}).encode()}
    with pytest.raises(IngestError, match="no views"):
        ingest(SCAN, root=tmp_path, base=BASE, get=served.__getitem__)
    assert not any(tmp_path.iterdir())


def test_reingest_replaces_the_item(tmp_path):
    (tmp_path / SCAN).mkdir()
    (tmp_path / SCAN / "stale.txt").write_text("old")
    item = ingest(SCAN, root=tmp_path, base=BASE, get=serve(manifest_with(NAMES[:2])).__getitem__)
    assert not (item / "stale.txt").exists() and len(list((item / "photos").iterdir())) == 2


def test_view_urls_prefers_the_grey_views():
    assert view_urls(manifest_with(["a"])) == [f"{public_url(f'views/{SCAN}', BASE)}/a_grey.png"]
