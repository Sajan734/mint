import json
import logging

import numpy as np
from PIL import Image

from eval.mask_strata import build, mask_fraction, merge_small, stratum_of
from tests.test_make_pairs import make_scene


def write_mask(path, frac, size=(100, 100)):
    arr = np.zeros(size, np.uint8)
    arr.flat[: int(frac * arr.size)] = 255
    Image.fromarray(arr).save(path)


def test_strata_by_mask_area_fraction(tmp_path):
    write_mask(tmp_path / "m.png", 0.05)
    assert abs(mask_fraction(tmp_path / "m.png") - 0.05) < 1e-9
    fracs = (0.0, 0.019, 0.02, 0.10, 0.101)
    assert [stratum_of(f) for f in fracs] == ["small", "small", "medium", "medium", "large"]


def test_stratum_under_12_merged_and_logged(caplog):
    groups = {"small": ["a"] * 3, "medium": ["b"] * 15, "large": ["c"] * 7}
    with caplog.at_level(logging.INFO, logger="eval.strata"):
        out = merge_small(groups)
    assert out == {"small+medium+large": ["a"] * 3 + ["b"] * 15 + ["c"] * 7}
    assert "merged stratum small" in caplog.text and "merged stratum large" in caplog.text


def test_changed_manifest_per_surviving_stratum(tmp_path):
    inst = make_scene(tmp_path, n_ref=30, n_test=26)
    for j in range(26):  # 13 small, 13 medium
        write_mask(inst / "gt_mask" / f"Inst_1_test_IMG_{j:03d}.png", 0.01 if j < 13 else 0.05)
    made = build(tmp_path, "Pots/Instance_1", tmp_path / "paslcd_pairs")
    assert set(made) == {"small", "medium"}
    assert len(json.loads(made["small"].read_text())) == 12
    summary = json.loads((tmp_path / "paslcd_pairs" / "pots_i1_strata.json").read_text())
    assert summary["counts"] == {"small": 13, "medium": 13}
