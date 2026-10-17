"""scripts/try_condition.py: photo-set discovery and the side-by-side table. No API calls."""

from PIL import Image as PILImage

from scripts.try_condition import photo_sets, table
from stages.condition import ViewAnswers, aggregates, build_condition, usable_pool


def _write(folder, n):
    folder.mkdir(parents=True)
    for i in range(n):
        PILImage.new("RGB", (400, 400)).save(folder / f"{i}.jpg")


def test_subfolders_become_items(tmp_path):
    _write(tmp_path / "clean", 2)
    _write(tmp_path / "worn", 3)
    assert {k: len(v) for k, v in photo_sets([tmp_path]).items()} == {"clean": 2, "worn": 3}


def test_flat_folder_gives_one_item_per_photo(tmp_path):
    _write(tmp_path / "flat", 2)
    assert sorted(photo_sets([tmp_path / "flat"])) == ["0", "1"]


def _run(wear, scratch):
    answers = [ViewAnswers(f"v{i}", nouls={"item_usable": 0.9, "scratches_scuffs": scratch, "stains_discolouration": 0.05,
                                           "cracks_tears": 0.03, "missing_broken": 0.02},
                           wear_score=wear, wear_probs={0: 0.5, 1: 0.5}, wear_confidence=0.8) for i in range(2)]
    condition, reasons = build_condition(answers)
    usable, pool = usable_pool(answers)
    return {"condition": condition, "reasons": reasons, "aggregates": aggregates(pool), "usable": len(usable), "views": 2}


def test_table_puts_sets_side_by_side():
    text = table({"clean": [_run(0.1, 0.05)], "worn": [_run(2.2, 0.9)]})
    header, grade_row = text.splitlines()[:2]
    assert "clean #1" in header and "worn #1" in header
    assert "like_new" in grade_row and "moderate_wear" in grade_row
