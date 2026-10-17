import json

from eval.make_paslcd_pairs import list_images
from eval.make_split_pairs import build, split_sides
from tests.test_make_pairs import make_scene


def test_even_odd_split_disjoint():
    names = [f"Inst_1_IMG_{i:03d}.JPG" for i in (5, 1, 3, 2, 4, 0)]
    seller, buyer = split_sides(names)
    assert seller == [f"Inst_1_IMG_{i:03d}.JPG" for i in (0, 2, 4)]
    assert buyer == [f"Inst_1_IMG_{i:03d}.JPG" for i in (1, 3, 5)]
    assert not set(seller) & set(buyer)


def test_pairs_never_same_image_and_twelve_pairs_nearest_centre(tmp_path):
    inst = make_scene(tmp_path)
    out = tmp_path / "paslcd_pairs" / "same" / "pairs.json"
    assert len(build(tmp_path, "Pots/Instance_1", out)) == 12
    src = json.loads((out.parent / "sources.json").read_text())
    refs = list_images(inst, "ref")
    for s in src:
        ia, ib = refs.index(s["a"]), refs.index(s["b"])
        assert ia != ib and ia % 2 == 0 and ib % 2 == 1
        assert abs(ia - ib) == 1  # cameras sit on a line, so the nearest buyer image is adjacent
