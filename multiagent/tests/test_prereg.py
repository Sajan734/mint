import pytest

from buyer_agent.aggregate import Thresholds
from eval.prereg import PREREG_PATH, PreregMismatch, check_frozen, read_prereg, thresholds_sha256

TUNE = {"Printing_area", "Porch"}
HELDOUT = {"Pots", "Zen"}


def test_hash_stable_and_key_order_independent():
    assert thresholds_sha256(Thresholds()) == thresholds_sha256(
        Thresholds(**dict(reversed(list(Thresholds().model_dump().items()))))
    )
    assert thresholds_sha256(Thresholds()) != thresholds_sha256(Thresholds(same=0.2))


def test_check_frozen_raises_on_any_threshold_change():
    check_frozen(Thresholds())
    for k, v in (("same", 0.2), ("support", 3), ("min_answered", 9), ("quality_frac", 0.8)):
        with pytest.raises(PreregMismatch):
            check_frozen(Thresholds(**{k: v}))


def test_prereg_template_hash_matches_default_thresholds():
    pre = read_prereg()
    assert pre.thresholds_sha256 == thresholds_sha256(Thresholds())
    assert pre.thresholds == Thresholds().model_dump()


def test_expected_json_matches_prereg_cases():
    cases = read_prereg().cases
    if not cases:
        pytest.skip("cases block is empty until U32")
    for c in cases:
        assert {"case", "split", "scene", "mode", "expected_label", "acceptable", "wrong"} <= set(c)
        assert c["expected_label"] in c["acceptable"] and not set(c["acceptable"]) & set(c["wrong"])


def test_cases_have_split_tune_or_heldout_and_scene_split_respected():
    assert PREREG_PATH.is_file()
    for c in read_prereg().cases:
        assert c["split"] in ("tune", "heldout")
        assert c["scene"] in (TUNE if c["split"] == "tune" else HELDOUT)
