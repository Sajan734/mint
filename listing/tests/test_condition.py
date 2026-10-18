"""condition stage: aggregation rules (fake per-view answers) and the with/without-baseline paths. No Jev calls."""

import asyncio
import json

import pytest
from PIL import Image as PILImage

import stages.condition as cond
from contracts import Baseline, Identity, RunContext, View, Views
from jev_questions import (
    CONDITION_CONTEXT,
    CONDITION_CONTEXT_NO_BASELINE,
    CONDITION_QUESTIONS,
    CONDITION_QUESTIONS_NO_BASELINE,
    condition_context,
    design_features,
    design_note,
)
from stages.condition import ViewAnswers, build_condition, grade_for, second_highest

CLEAN = {"item_usable": 0.95, "scratches_scuffs": 0.05, "stains_discolouration": 0.05,
         "cracks_tears": 0.03, "missing_broken": 0.03}


def view(i, wear=1.0, probs=None, conf=0.8, **nouls):
    return ViewAnswers(
        view_id=f"v{i:02d}", nouls=CLEAN | nouls, wear_score=wear,
        wear_probs=probs or {0: 0.1, 1: 0.8, 2: 0.1, 3: 0.0}, wear_confidence=conf,
    )


def twelve(**overrides):
    return [view(i, **overrides) for i in range(12)]


def test_second_highest():
    assert second_highest([0.1, 0.9, 0.5]) == 0.5
    assert second_highest([0.7]) == 0.7


@pytest.mark.parametrize("score, grade", [(0.0, "like_new"), (0.49, "like_new"), (0.5, "light_wear"),
                                          (1.49, "light_wear"), (2.0, "moderate_wear"), (2.6, "heavy_wear")])
def test_grade_bands(score, grade):
    assert grade_for(score) == grade


LIKE_NEW = {0: 0.9, 1: 0.08, 2: 0.02, 3: 0.0}
WORN = {0: 0.0, 1: 0.15, 2: 0.7, 3: 0.15}


def test_clean_item_is_like_new_with_no_defects():
    condition, reasons = build_condition(twelve(wear=0.1, probs=LIKE_NEW, conf=0.9))
    assert condition.grade == "like_new"
    assert condition.grade_score == 0.9 and condition.grade_confidence == 0.9
    assert condition.defects == [] and condition.usable_view_count == 12
    assert condition.needs_seller_check is False and reasons == []


def test_worn_item_gets_worn_grade_and_its_defects():
    answers = [view(i, wear=2.1, probs=WORN, conf=0.75) for i in range(12)]
    for i in (1, 2, 3, 9):  # scuffs visible from the right side and above
        answers[i] = view(i, wear=2.1, probs=WORN, conf=0.75, scratches_scuffs=0.92)
    for i in (5, 6):  # a stain on the left ear cup
        answers[i] = view(i, wear=2.1, probs=WORN, conf=0.75, stains_discolouration=0.85)
    condition, reasons = build_condition(answers)
    assert condition.grade == "moderate_wear"
    assert {d.kind: d.view_ids for d in condition.defects} == {
        "scratch": ["v01", "v02", "v03", "v09"],
        "stain": ["v05", "v06"],
    }
    assert condition.needs_seller_check is False and reasons == []


def test_light_wear_views_without_check():
    condition, reasons = build_condition(twelve())
    assert condition.grade == "light_wear"
    assert condition.grade_score == 0.8 and condition.grade_confidence == 0.8
    assert condition.defects == [] and condition.usable_view_count == 12
    assert condition.needs_seller_check is False and reasons == []


def test_defect_in_only_one_view_is_not_reported():
    answers = twelve()
    answers[3] = view(3, cracks_tears=0.97)
    condition, reasons = build_condition(answers)
    assert condition.defects == []
    assert condition.needs_seller_check is False and reasons == []  # not even an "unsure" flag


def test_defect_seen_in_two_views_is_reported_with_its_views():
    answers = twelve()
    answers[2] = view(2, scratches_scuffs=0.9)
    answers[5] = view(5, scratches_scuffs=0.8)
    condition, reasons = build_condition(answers)
    (d,) = condition.defects
    assert (d.kind, d.score, d.view_ids) == ("scratch", 0.8, ["v02", "v05"])
    assert reasons == []


def test_unsure_defect_asks_the_seller():
    answers = twelve()
    answers[0] = view(0, stains_discolouration=0.55)
    answers[1] = view(1, stains_discolouration=0.52)
    condition, reasons = build_condition(answers)
    assert condition.needs_seller_check is True
    assert any("stains_discolouration" in r for r in reasons)


def test_wear_uses_second_highest_view():
    answers = twelve(wear=0.2, probs={0: 0.8, 1: 0.2, 2: 0.0, 3: 0.0})
    answers[4] = view(4, wear=2.8)  # one heavy-looking view alone doesn't decide
    assert build_condition(answers)[0].grade == "like_new"
    answers[7] = view(7, wear=2.2)
    assert build_condition(answers)[0].grade == "moderate_wear"


def test_unusable_views_are_ignored_and_too_few_flags():
    answers = [view(i, item_usable=0.2, scratches_scuffs=0.99) for i in range(8)] + [view(i) for i in range(8, 12)]
    condition, reasons = build_condition(answers)
    assert condition.usable_view_count == 4 and condition.defects == []
    assert condition.needs_seller_check is True and any("usable" in r for r in reasons)


@pytest.mark.parametrize("usable_count, flagged", [(5, True), (6, False)])
def test_too_few_usable_views_boundary(usable_count, flagged):
    answers = [view(i) for i in range(usable_count)] + [view(i, item_usable=0.3) for i in range(usable_count, 12)]
    condition, reasons = build_condition(answers)
    assert condition.usable_view_count == usable_count
    assert condition.needs_seller_check is flagged
    assert any("usable" in r for r in reasons) is flagged


def test_no_usable_view_still_grades_from_all_answered_views():
    condition, _ = build_condition([view(i, item_usable=0.1) for i in range(12)])
    assert condition.usable_view_count == 0 and condition.needs_seller_check is True


def test_failed_views_are_skipped_but_all_failing_raises():
    answers = twelve()
    answers[0] = ViewAnswers("v00", error="TypeSafeError: boom")
    assert build_condition(answers)[0].usable_view_count == 11
    with pytest.raises(RuntimeError, match="none of the views"):
        build_condition([ViewAnswers("v00", error="x")])


def test_no_baseline_questions_never_mention_baseline():
    assert "`baseline`" not in CONDITION_CONTEXT_NO_BASELINE
    assert "`baseline`" in CONDITION_CONTEXT
    assert set(CONDITION_QUESTIONS_NO_BASELINE) == set(CONDITION_QUESTIONS)
    for q in CONDITION_QUESTIONS_NO_BASELINE.values():
        assert "`baseline`" not in json.dumps(q.model_dump())


# --- stage paths (Jev replaced) ----------------------------------------------------------------


@pytest.fixture
def fake_jev(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def ask(jev, v, context, questions, baseline_image):
        calls.append({"view": v.view_id, "context": context, "questions": questions, "baseline": baseline_image})
        return view(int(v.view_id[1:]))

    monkeypatch.setattr(cond, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(cond, "ask_view", ask)
    monkeypatch.setattr(cond, "_jev_key", lambda: "test-key")
    return calls


def make_ctx(tmp_path):
    item = tmp_path / "item"
    item.mkdir(exist_ok=True)
    return RunContext(item_id="item", item_dir=item, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")


VIEWS = Views(item_id="item", views=[View(view_id=f"v{i:02d}", label="x", image_path=f"v{i:02d}.png") for i in range(12)])


def test_missing_baseline_runs_view_only_questions(fake_jev, tmp_path):
    ctx = make_ctx(tmp_path)
    baseline = Baseline(query="q", image_path=None, source="image_search", note="nothing found")
    condition = asyncio.run(cond.condition(ctx, VIEWS, baseline))
    assert condition.grade == "light_wear"
    assert len(fake_jev) == 12
    assert all(c["baseline"] is None and c["context"] == CONDITION_CONTEXT_NO_BASELINE for c in fake_jev)
    assert all(c["questions"] is CONDITION_QUESTIONS_NO_BASELINE for c in fake_jev)
    raw = json.loads((ctx.run_dir / "condition_raw.json").read_text())
    assert raw["baseline_used"] is False and len(raw["views"]) == 12


def test_with_baseline_sends_it_to_every_view(fake_jev, tmp_path):
    ctx = make_ctx(tmp_path)
    photo = tmp_path / "baseline.jpg"
    PILImage.new("RGB", (800, 800), (250, 250, 250)).save(photo)
    baseline = Baseline(query="q", image_path=str(photo), source="manual")
    asyncio.run(cond.condition(ctx, VIEWS, baseline))
    assert all(c["baseline"] is not None and c["context"] == CONDITION_CONTEXT for c in fake_jev)
    assert all(c["questions"] is CONDITION_QUESTIONS for c in fake_jev)


MOUSE = Identity(category="wireless mouse", brand="ThinkPad", visible_text=["ThinkPad"],
                 attributes={"colour": "black, red", "connectivity": "wireless", "scroll_wheel_colour": "red"},
                 search_query="ThinkPad wireless mouse", confidence=0.9)


def test_design_features_come_from_identify():
    assert design_features(MOUSE) == ["printed text or logos reading 'ThinkPad'",
                                      "these colours: colour black, red; scroll wheel colour red"]
    assert design_features(None) == []
    plain = Identity(category="mug", search_query="mug", confidence=0.5)
    assert design_features(plain) == [] and design_note(plain) == ""


def test_identity_tells_jev_the_printing_is_design(fake_jev, tmp_path):
    ctx = make_ctx(tmp_path)
    baseline = Baseline(query="q", image_path=None, source="image_search", note="nothing found")
    asyncio.run(cond.condition(ctx, VIEWS, baseline, MOUSE))
    context = fake_jev[0]["context"]
    assert context.startswith(CONDITION_CONTEXT_NO_BASELINE)
    assert "'ThinkPad'" in context and "not scratches, scuffs or stains" in context
    assert all(c["context"] == context for c in fake_jev)
    raw = json.loads((ctx.run_dir / "condition_raw.json").read_text())
    assert "'ThinkPad'" in raw["design_note"]


def test_design_note_goes_with_a_baseline_too():
    assert condition_context(True, MOUSE) == CONDITION_CONTEXT + design_note(MOUSE)
