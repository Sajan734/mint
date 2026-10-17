import pytest

from eval.stats import class_counts, false_same, spread, wilson


def test_wilson_known_values():
    lo, hi = wilson(0, 3)  # 3/3 correct has the same interval mirrored
    assert lo == 0.0 and hi == pytest.approx(0.5610, abs=1e-3)
    lo, hi = wilson(3, 3)
    assert lo == pytest.approx(0.4390, abs=1e-3) and hi == 1.0  # the "about 0.44" in AM-22
    lo, hi = wilson(5, 10)
    assert (lo, hi) == pytest.approx((0.2366, 0.7634), abs=1e-3)


def test_wilson_empty_and_invalid():
    assert wilson(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson(4, 3)


def test_class_counts_sorted():
    assert class_counts(["same", "different", "same"]) == {"different": 1, "same": 2}
    assert class_counts([]) == {}


def test_false_same_counts_only_changed_cases():
    exp = ["same", "different", "different", "same"]
    got = ["same", "same", "different", "different"]
    assert false_same(exp, got) == (1, 2)


def test_false_same_no_changed_cases_and_length_mismatch():
    assert false_same(["same"], ["same"]) == (0, 0)
    with pytest.raises(ValueError):
        false_same(["same"], [])


def test_spread():
    assert spread([0.0, 0.5, 0.25]) == (0.0, 0.5, 0.5)
    assert spread([]) == (0.0, 0.0, 0.0)
