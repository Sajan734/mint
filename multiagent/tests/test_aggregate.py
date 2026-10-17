import random

import pytest
from pydantic import ValidationError

from buyer_agent.aggregate import Thresholds, aggregate
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.models import AlignmentMetrics, JevViewScores, ViewFailure


def view(name, vp=0.95, q=0.95, shape=0.05, part=0.05, color=0.05, any_=0.05):
    return JevViewScores(
        view=name,
        model="jev-1.13.0",
        viewpoint_match=vp,
        scan_quality_ok=q,
        shape_diff=shape,
        part_diff=part,
        color_diff=color,
        any_diff=any_,
        latency_ms=1,
    )


def views(n=12, **kw):
    return [view(f"v{i}", **kw) for i in range(n)]


def run(scores, requested=12, failures=(), alignment=None, mode="icp", th=None):
    return aggregate(scores, list(failures), requested, alignment, mode, th)


def test_all_quiet_is_same():
    v = run(views())
    assert v.label == "same" and v.evidence_score == pytest.approx(0.95)


def test_two_views_part_diff_is_different():
    s = views()
    s[0], s[1] = view("left", part=0.9, any_=0.9), view("front-left", part=0.85, any_=0.85)
    v = run(s)
    assert v.label == "different" and v.evidence.categories["part_diff"].views == [
        "left",
        "front-left",
    ]
    assert v.evidence.flagged == ["part_diff"] and "any_diff" not in v.reason


def test_support_1_reason_says_one_view():
    v = run(
        [view("a", shape=0.9)] + views(11)[1:] and [view("a", shape=0.9)] + views(11),
        th=Thresholds(support=1),
    )
    assert v.label == "different" and "one view" in v.reason


def test_mixed_signal_is_different():
    v = run(views(shape=0.4))
    assert v.label == "different" and v.cause is None and "shape_diff" in v.reason
    assert v.evidence_score == pytest.approx(0.4 * 12 / 12)


def test_match_boundary_030_same_031_different():
    assert run(views(shape=0.30)).label == "same"
    assert run(views(shape=0.30)).evidence_score == pytest.approx(0.70)
    v = run(views(shape=0.31))
    assert v.label == "different" and v.cause is None


def test_misaligned_gate_is_different_with_cause():
    s = [view(f"m{i}", vp=0.1) for i in range(8)] + views(4)
    v = run(s, requested=12)
    assert (v.label, v.cause, v.evidence_score) == ("different", "misaligned", 0.0)
    assert v.evidence.usable_views == 4


def test_low_usable_fraction_forces_different_with_caveat():
    s = views(8) + [view(f"x{i}", vp=0.1) for i in range(4)]
    v = run(s)
    assert v.evidence.usable_views == 8 and v.label == "different" and v.cause is None
    assert any("less certain" in c for c in v.caveats)


def test_lone_strong_view_is_same_with_caveat():
    v = run([view("a", shape=0.9)] + views(11))
    assert v.label == "same" and any("one view only" in c for c in v.caveats)


def test_any_diff_alone_counts_in_the_score():
    s = [view("a", any_=0.9), view("b", any_=0.9)] + views(10)
    v = run(s)
    assert v.label == "different" and v.evidence.flagged == []
    assert v.evidence_score == pytest.approx(0.9)


def test_quality_gate_needs_75pct():
    ok = views(9) + [view(f"q{i}", q=0.1) for i in range(3)]
    assert run(ok).label == "same"  # 9 == ceil(.75*12)
    bad = views(8) + [view(f"q{i}", q=0.1) for i in range(4)]
    v = run(bad)
    assert (v.label, v.cause, v.evidence_score) == ("different", "low_quality", 0.0)


def test_evidence_score_formula_uses_usable_over_requested():
    d = run([view("a", part=0.8), view("b", part=0.8)] + views(10), requested=16)
    assert d.label == "different" and d.evidence_score == pytest.approx(0.8 * 12 / 16)
    s = run(views(), requested=16)  # same: match score, coverage is not applied
    assert s.label == "same" and s.evidence_score == pytest.approx(0.95)


def test_duplicate_view_labels_rejected():
    with pytest.raises(AgentError) as e:
        run([view("a")] * 12)
    assert e.value.code == ErrorCode.INPUT_INVALID


def test_threshold_validators():
    for bad in (
        {"match_min": 1.5},
        {"support": 7},
        {"min_views": 13},
        {"quality_frac": 0.4},
        {"same_usable_frac": 1.1},
        {"support": 0},
    ):
        with pytest.raises(ValidationError):
            Thresholds(**bad)


def test_fewer_than_min_answered_raises_jev_unavailable():
    with pytest.raises(AgentError) as e:
        run(views(7), requested=12)
    assert e.value.code == ErrorCode.JEV_UNAVAILABLE


def test_ambiguity_is_a_caveat_not_an_override():
    al = AlignmentMetrics(rmse=0.1, a_covered=0.9, b_covered=0.9, ambiguity=0.9, scale=1.0)
    v = run(views(), alignment=al)
    assert v.label == "same" and any("symmetric" in c for c in v.caveats)
    diff = [view("a", part=0.9), view("b", part=0.9)] + views(10)
    assert run(diff, alignment=al).label == "different"


def test_caveats_dent_always_failed_views_when_any():
    f = [ViewFailure(view="z", code="JEV_TIMEOUT")]
    v = run(views(), requested=13, failures=f, mode="skipped_view_pairs")
    assert "dent" in v.caveats[0] and "1 view could not be checked." in v.caveats
    assert v.evidence.alignment_mode == "skipped_view_pairs" and len(v.caveats) == 3
    assert len(run(views()).caveats) == 1


def _random_scores(rng, n):
    def p():
        return rng.choice([rng.random(), rng.random() * 0.2, 0.9])

    return [
        view(f"r{i}", vp=p(), q=p(), shape=p(), part=p(), color=p(), any_=p()) for i in range(n)
    ]


def test_property_answered_below_min_never_same():
    rng = random.Random(0)
    for _ in range(2000):
        s = _random_scores(rng, rng.randint(0, 7))
        with pytest.raises(AgentError):
            run(s, requested=12)


def test_property_usable_below_75pct_never_same():
    rng = random.Random(0)
    for _ in range(2000):
        s = _random_scores(rng, rng.randint(8, 12))
        v = run(s)
        if v.label == "same":
            assert v.evidence.usable_views * 4 >= 3 * len(s)


def test_property_lone_strong_view_scored_by_second_highest():
    rng = random.Random(0)
    for _ in range(2000):
        n = rng.randint(8, 12)
        s = [
            view(
                f"l{i}",
                shape=rng.random() * 0.2,
                part=rng.random() * 0.2,
                color=rng.random() * 0.2,
                any_=rng.random() * 0.2,
            )
            for i in range(n)
        ]
        k = rng.randrange(n)
        cat = rng.choice(["shape", "part", "color", "any_"])
        s[k] = view(f"l{k}", **{cat: rng.uniform(0.5, 1.0)})
        v = run(s, requested=n)  # one strong view cannot reach the 2nd-highest evidence
        assert v.label == "same" or v.cause is not None or v.evidence.usable_views < n


def test_property_quality_poor_or_misaligned_never_same():
    rng = random.Random(0)
    for _ in range(2000):
        n = rng.randint(8, 12)
        bad_kind = rng.choice(["q", "vp"])
        n_bad = rng.randint(n // 2, n)
        s = [view(f"b{i}", **{bad_kind: rng.random() * 0.4} if i < n_bad else {}) for i in range(n)]
        v = run(s, requested=n)
        if n - n_bad < max(6, -(-3 * n // 4)):
            assert v.label == "different"


def test_unknown_alignment_mode_rejected_not_defaulted():
    with pytest.raises(AgentError) as e:
        run(views(), mode="skiped_view_pairs")
    assert e.value.code is ErrorCode.INPUT_INVALID
