"""match_gate: aggregation and decision rules (fake per-view answers), stage paths with a fake Jev. No API calls."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image as PILImage

import stages.match_gate as mg
from contracts import Baseline, RunContext, View, Views
from stages.identify import MissingKeyError
from stages.match_gate import (
    REASONS,
    THRESHOLDS,
    GateAggregate,
    GateRaw,
    GateViewAnswer,
    aggregate,
    build_match_check,
    decide,
    load_raw,
)

ROOT = Path(__file__).resolve().parent.parent


def answer(i, product=0.9, category=0.95, usable=0.9, error=None):
    return GateViewAnswer(view_id=f"v{i:02d}", item_usable=usable, same_category=category,
                          same_product=product, error=error)


def agg(category, product, usable=12, total=12):
    return GateAggregate(category, product, usable, total)


# --- aggregate --------------------------------------------------------------------------------


def test_category_median_product_second_highest():
    views = [answer(i, product=p, category=c) for i, (p, c) in
             enumerate([(0.9, 0.2), (0.8, 0.9), (0.1, 0.95), (0.3, 0.97), (0.2, 0.99), (0.5, 0.96)])]
    a = aggregate(views)
    assert a.same_product == 0.8
    assert a.same_category == pytest.approx(0.955)
    assert (a.usable_views, a.total_views) == (6, 6)


def test_unusable_and_failed_views_are_ignored():
    views = [answer(i) for i in range(6)]
    views += [answer(6, product=0.99, usable=0.3), answer(7, product=0.99, usable=0.3), answer(8, error="boom")]
    a = aggregate(views)
    assert (a.usable_views, a.total_views) == (6, 9)
    assert a.same_product == 0.9


def test_no_usable_views():
    assert aggregate([answer(0, usable=0.1)]) == GateAggregate(None, None, 0, 1)


def test_product_seen_from_its_photographed_side_matches():
    # The baseline shows one side: 3 facing views agree, the other 9 can't see that side.
    views = [answer(i, product=0.9) for i in range(3)] + [answer(i, product=0.2) for i in range(3, 12)]
    assert decide(aggregate(views))[0] == "match"


def test_one_stray_high_view_does_not_match():
    views = [answer(0, product=0.95)] + [answer(i, product=0.2) for i in range(1, 12)]
    assert decide(aggregate(views))[0] == "mismatch"


# --- decide -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, expected",
    [
        (agg(0.95, 0.05, usable=5), ("uncertain", "too_few_views")),  # too few views wins over a low score
        (agg(None, None, usable=0), ("uncertain", "too_few_views")),
        (agg(0.29, 0.90), ("mismatch", "different_kind")),
        (agg(0.95, 0.29), ("mismatch", "different_product")),
        (agg(0.30, 0.30), ("uncertain", "uncertain")),  # 0.30 itself is not a mismatch
        (agg(0.95, 0.60), ("match", "match")),
        (agg(0.95, 0.59), ("uncertain", "uncertain")),
        # Run-to-run noise around 0.5 never flips the verdict.
        (agg(0.95, 0.48), ("uncertain", "uncertain")),
        (agg(0.95, 0.52), ("uncertain", "uncertain")),
        (agg(0.95, 0.91, usable=6), ("match", "match")),
    ],
)
def test_decide(a, expected):
    assert decide(a) == expected


def test_threshold_overrides():
    a = agg(0.95, 0.62)
    assert decide(a)[0] == "match"
    assert decide(a, THRESHOLDS | {"match_min": 0.65})[0] == "uncertain"
    assert decide(agg(0.95, 0.9, usable=5), THRESHOLDS | {"min_usable_views": 5})[0] == "match"


@pytest.mark.parametrize("key", ["different_kind", "different_product", "too_few_views", "match", "uncertain"])
def test_reasons_are_short_and_name_the_query(key):
    text = REASONS[key].format(query="Sony WH-1000XM4")
    assert "Sony WH-1000XM4" in text and len(text) <= 160


def test_mismatch_carries_plain_reason():
    raw = GateRaw(views=[answer(i, product=0.1) for i in range(12)])
    check = build_match_check(raw, "Sony WH-1000XM4")
    assert check.verdict == "mismatch"
    assert check.reason.startswith("This scan looks like a different model from Sony WH-1000XM4.")
    assert check.same_product == 0.1


def test_no_baseline_is_uncertain_without_scores():
    baseline = Baseline(query="Sony WI-XB400", image_path=None, source="image_search", note="nothing found")
    check = asyncio.run(mg.match_gate(None, None, baseline))  # never touches ctx or views
    assert check.verdict == "uncertain"
    assert check.same_category is None and check.same_product is None
    assert "reference photo for Sony WI-XB400" in check.reason


# --- fixture stubs and replay -------------------------------------------------------------------


@pytest.mark.parametrize("item, verdict", [("item01", "match"), ("item02", "mismatch")])
def test_fixture_stubs(item, verdict):
    raw = load_raw(json.loads((ROOT / "fixtures" / item / "stubs" / "match_gate.json").read_text()))
    assert build_match_check(raw, "q").verdict == verdict


def test_load_raw_ignores_saved_extras():
    raw = load_raw({"views": [answer(0).model_dump()], "query": "q", "aggregate": {}, "verdict": "x",
                    "thresholds": {}, "model": "jev-latest"})
    assert raw.query == "q" and len(raw.views) == 1


def test_replay_script_and_overrides():
    stub = str(ROOT / "fixtures" / "item01" / "stubs" / "match_gate.json")
    run = lambda *extra: subprocess.run([sys.executable, "scripts/replay_match_gate.py", stub, *extra],  # noqa: E731
                                        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert "match " in run()
    assert "uncertain" in run("--set", "match_min=0.9")


# --- live path with a fake Jev -------------------------------------------------------------------


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

    async def ask(jev, view, baseline_image):
        calls.append((view.view_id, baseline_image))
        return calls_answer(view)

    calls_answer = lambda view: answer(int(view.view_id[1:]))  # noqa: E731
    monkeypatch.setattr(mg, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(mg, "ask_view", ask)
    monkeypatch.setattr(mg, "_jev_key", lambda: "test-key")
    return calls


VIEWS = Views(item_id="item", views=[View(view_id=f"v{i:02d}", label="x", azimuth_deg=0, elevation_deg=10,
                                          image_path=f"v{i:02d}.png") for i in range(12)])


def live_setup(tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    photo = tmp_path / "baseline.jpg"
    PILImage.new("RGB", (800, 800), (250, 250, 250)).save(photo)
    ctx = RunContext(item_id="item", item_dir=item, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    return ctx, Baseline(query="Sony WH-CH510", image_path=str(photo), source="manual")


def test_live_path_asks_every_view_and_saves_raw(fake_jev, tmp_path):
    ctx, baseline = live_setup(tmp_path)
    check = asyncio.run(mg.match_gate(ctx, VIEWS, baseline))
    assert check.verdict == "match"
    assert len(fake_jev) == 12 and all(b is not None for _, b in fake_jev)
    saved = json.loads((ctx.run_dir / "match_gate_raw.json").read_text())
    assert len(saved["views"]) == 12 and saved["verdict"] == "match"
    assert saved["query"] == "Sony WH-CH510" and saved["thresholds"] == THRESHOLDS
    assert build_match_check(load_raw(saved), "Sony WH-CH510") == check  # replayable


def test_all_views_failing_is_uncertain_not_a_crash(monkeypatch, tmp_path):
    ctx, baseline = live_setup(tmp_path)
    monkeypatch.setattr(mg, "_jev_key", lambda: "test-key")

    class FailingClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def system_one(self, **k):
            from typesafe_sdk import TypeSafeError

            raise TypeSafeError("service down")

    monkeypatch.setattr(mg, "AsyncTypeSafeClient", FailingClient)
    views = Views(item_id="item", views=[View(view_id="v00", label="x", azimuth_deg=0, elevation_deg=10,
                                              image_path=baseline.image_path)])
    check = asyncio.run(mg.match_gate(ctx, views, baseline))
    assert check.verdict == "uncertain" and "Too few clear views" in check.reason
    saved = json.loads((ctx.run_dir / "match_gate_raw.json").read_text())
    assert "service down" in saved["views"][0]["error"]


def test_missing_key_fails_early(monkeypatch, tmp_path):
    ctx, baseline = live_setup(tmp_path)
    monkeypatch.setattr(mg, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="TYPESAFE_API_KEY"):
        asyncio.run(mg.match_gate(ctx, VIEWS, baseline))
