import json

import numpy as np
from PIL import Image

from eval.make_paslcd_pairs import build, greedy_nearest_pairs, list_images, registered_counts
from tests.test_colmap_bin import write_images_bin


def make_scene(root, scene="Pots/Instance_1", n_ref=24, n_test=14):
    """Cameras on the x axis: ref i at x=i, test j at x=1.7*j+0.2."""
    inst = root / "paslcd" / scene
    (inst / "images").mkdir(parents=True)
    (inst / "gt_mask").mkdir()
    cams = {f"Inst_1_IMG_{i:03d}.JPG": (float(i), 0.0, 0.0) for i in range(n_ref)}
    for j in range(n_test):
        cams[f"Inst_1_test_IMG_{j:03d}.JPG"] = (j * 1.7 + 0.2, 0.0, 0.0)
    for name in cams:
        Image.new("RGB", (400, 300), (10, 120, 200)).save(inst / "images" / name, "JPEG")
    write_images_bin(inst / "sparse" / "0" / "images.bin", cams)
    return inst


def test_greedy_unique_nearest_pairs():
    a = np.array([[0, 0, 0], [10, 0, 0], [20, 0, 0]], float)
    b = np.array([[0.1, 0, 0], [0.2, 0, 0], [19, 0, 0]], float)
    pairs = greedy_nearest_pairs(a, b, n=3)
    assert (0, 0) in pairs and (2, 2) in pairs
    assert len({i for i, _ in pairs}) == len({j for _, j in pairs}) == 3


def test_manifest_has_12_entries_relative_paths(tmp_path):
    make_scene(tmp_path)
    out = tmp_path / "paslcd_pairs" / "case" / "pairs.json"
    build(tmp_path, "Pots/Instance_1", "Pots/Instance_1", "ref", "test", out)
    entries = json.loads(out.read_text())
    assert len(entries) == 12
    assert [e["label"] for e in entries][:2] == ["view_01", "view_02"]
    for e in entries:
        for side in ("a", "b"):
            assert not e[side].startswith("/") and ":" not in e[side]
            assert (tmp_path / e[side]).is_file()
            assert max(Image.open(tmp_path / e[side]).size) <= 1024


def test_registered_counts_and_listing(tmp_path):
    inst = make_scene(tmp_path)
    assert registered_counts(inst) == (24, 14)
    assert len(list_images(inst, "ref")) == 24 and len(list_images(inst, "test")) == 14


def test_cross_scene_pairs_unposed_index_order(tmp_path):
    make_scene(tmp_path, "Pots/Instance_1")
    make_scene(tmp_path, "Zen/Instance_1")
    out = tmp_path / "paslcd_pairs" / "x" / "pairs.json"
    build(tmp_path, "Pots/Instance_1", "Zen/Instance_1", "ref", "ref", out)
    assert len(json.loads(out.read_text())) == 12
