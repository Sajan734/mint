"""The highlight stage's decisions (boxes, selection, checks) on hand-made inputs, and a whole stage run with Gemini,
the lift and the debug render faked. No API or GPU calls."""

import asyncio
import io
import json

import numpy as np
import pytest
from PIL import Image as PILImage, ImageDraw
from pydantic import ValidationError

import stages.highlight as hl
from contracts import Baseline, Defect, DefectBox, View, Views
from stages.highlight import (
    HIGHLIGHT,
    Box,
    Lifted,
    boxes_schema,
    camera_diff,
    ellipse_mask,
    kinds_by_view,
    parse_boxes,
    red_shares,
    select,
    widen,
)
from tests.test_splat_render import gaussians, ply_bytes

# --- boxes ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lo, hi, expected",
    [(0.2, 0.4, (0.2, 0.4)), (0.5, 0.51, (0.49, 0.52)), (0.99, 1.0, (0.97, 1.0)), (0.0, 0.005, (0.0, 0.03))],
)
def test_widen_to_the_minimum_side(lo, hi, expected):
    assert widen(lo, hi, 0.03) == pytest.approx(expected)


def test_box_from_gemini_format():
    box = Box.of(2, DefectBox(kind="scratch", box_2d=[100, 200, 300, 400]), 0.03)
    assert (box.view, box.kind, box.top, box.left, box.bottom, box.right) == (2, "scratch", 0.1, 0.2, 0.3, 0.4)


@pytest.mark.parametrize("box_2d", [[300, 200, 100, 400], [100, 400, 300, 400], [0, 0, 1001, 10], [1, 2, 3]])
def test_bad_boxes_are_invalid(box_2d):
    with pytest.raises(ValidationError):
        DefectBox(kind="scratch", box_2d=box_2d)


def test_ellipse_mask_is_inscribed_in_the_box():
    mask = ellipse_mask(Box(0, "scratch", 0.25, 0.25, 0.75, 0.75), 100)
    assert mask[50, 50] == 255 and mask[26, 26] == 0 and mask[10, 50] == 0
    assert (mask > 0).sum() == pytest.approx(np.pi * 25 * 25, rel=0.03)


def test_parse_boxes_keeps_valid_boxes_of_the_asked_kinds():
    raw = {"boxes": [
        {"kind": "scratch", "box_2d": [10, 10, 50, 50]},
        {"kind": "stain", "box_2d": [10, 10, 50, 50]},  # not asked for here
        {"kind": "scratch", "box_2d": [50, 10, 10, 50]},  # empty
        *({"kind": "scratch", "box_2d": [i, 0, i + 5, 5]} for i in range(10, 60, 10)),
    ]}
    boxes, dropped = parse_boxes(raw, ["scratch"], 4)
    assert len(boxes) == 4 and all(b.kind == "scratch" for b in boxes)
    reasons = [d["reason"] for d in dropped]
    assert "stain was not asked for in this view" in reasons
    assert any(r.startswith("invalid") for r in reasons)
    assert any("4-box limit" in r for r in reasons)
    assert parse_boxes({}, ["scratch"], 4) == ([], [])


def test_schema_offers_only_the_asked_kinds():
    schema = boxes_schema(["scratch", "crack"])
    box = schema["properties"]["boxes"]["items"]
    assert box["properties"]["kind"]["enum"] == ["scratch", "crack"]
    assert box["required"] == ["kind", "box_2d"]


def make_views(n=4):
    return Views(item_id="t", views=[View(view_id=f"v{i:02d}", label=f"view {i}", azimuth_deg=45 * i,
                                          elevation_deg=10, image_path=f"v{i:02d}.png") for i in range(n)])


def test_kinds_by_view_in_render_order():
    defects = [Defect(kind="crack", score=0.9, view_ids=["v02", "v00"]),
               Defect(kind="scratch", score=0.7, view_ids=["v02"]),
               Defect(kind="stain", score=0.8, view_ids=[])]
    assert kinds_by_view(defects, make_views()) == {"v00": ["crack"], "v02": ["crack", "scratch"]}


# --- selection --------------------------------------------------------------------------------


def lifted(seen, hit, gap, item_px=(1000.0, 1000.0), rendered=1000):
    seen, hit, gap = (np.asarray(a, dtype=np.float32) for a in (seen, hit, gap))
    return Lifted(gaussians=rendered, rendered=rendered, ids=np.arange(seen.shape[1]), seen=seen, hit=hit,
                  depth_gap=gap, item_px=np.asarray(item_px), mask_item_px=np.full(len(hit), 50.0))


# Two views, one scratch box in each (rows 0 and 1). Candidates:
#   0 inside both boxes; 1 inside view 0's box only; 2 shows in view 0 only, inside its box;
#   3 inside both boxes' footprints but hidden behind the surface in both views
SEEN = [[10, 10, 10, 10], [10, 10, 0, 10]]
HIT = [[10, 10, 10, 10], [0, 0, 0, 0]]
HIT[1] = [10, 0, 0, 10]
GAP = [[0, 0, 0, 0.8], [0, 0, np.inf, 0.8]]
BOXES = [Box(0, "scratch", 0.1, 0.1, 0.3, 0.3), Box(1, "scratch", 0.1, 0.1, 0.3, 0.3)]


def test_select_needs_agreement_across_the_views_that_show_it():
    chosen = select(lifted(SEEN, HIT, GAP), BOXES, [0, 1], {"scratch": [0, 1]})
    assert chosen["scratch"].tolist() == [True, False, True, False]


def test_hidden_gaussians_are_never_selected():
    gap = [[0.8] * 4, [0.8] * 4]  # everything behind the surface in both views
    assert not select(lifted(SEEN, HIT, gap), BOXES, [0, 1], {"scratch": [0, 1]})["scratch"].any()


def test_a_view_not_searched_for_a_kind_doesnt_vote_on_it():
    # view 1 was only asked about stains, so it says nothing about scratches
    chosen = select(lifted(SEEN, HIT, GAP), BOXES[:1], [0], {"scratch": [0], "stain": [1]})
    assert chosen["scratch"].tolist() == [True, True, True, False]
    assert not chosen["stain"].any()


def test_dropped_boxes_dont_mark_anything():
    chosen = select(lifted(SEEN, HIT, GAP), BOXES, [1], {"scratch": [1]})
    assert chosen["scratch"].tolist() == [True, False, False, False]


CHECK_ALL = HIGHLIGHT | {"confirm_min_checked": 1}


def test_a_box_the_other_view_sees_and_leaves_alone_is_dropped_whole():
    """The real-scan case: a logo boxed as a scratch at a grazing angle in one view, seen plainly and left unboxed
    in the other. Without confirmation its fringe (the part only the first view sees) would be tinted."""
    seen = [[10, 10, 10, 10], [10, 10, 10, 0]]  # candidate 3 shows only in view 0
    hit = [[10, 10, 10, 10]]
    gap = [[0.0] * 4, [0.0] * 4]
    lift = lifted(seen, hit, gap)
    boxes = BOXES[:1]
    confirmed, rates = hl.confirmed_boxes(lift, boxes, [0], {"scratch": [0, 1]}, CHECK_ALL)
    assert confirmed == [] and rates == {0: 0.0}
    assert not select(lift, boxes, [0], {"scratch": [0, 1]}, CHECK_ALL, confirmed)["scratch"].any()
    # without the confirmation step, the fringe only view 0 sees would survive the per-Gaussian vote
    assert select(lift, boxes, [0], {"scratch": [0, 1]}, CHECK_ALL)["scratch"].tolist() == [False] * 3 + [True]


def test_boxes_that_agree_are_confirmed():
    confirmed, rates = hl.confirmed_boxes(lifted(SEEN, HIT, GAP), BOXES, [0, 1], {"scratch": [0, 1]}, CHECK_ALL)
    assert confirmed == [0, 1] and rates == {0: 0.5, 1: 1.0}


def test_too_little_overlap_is_no_evidence_either_way():
    confirmed, rates = hl.confirmed_boxes(lifted(SEEN, HIT, GAP), BOXES, [0, 1], {"scratch": [0, 1]})
    assert confirmed == [0, 1] and rates == {0: None, 1: None}  # fewer than confirm_min_checked seen elsewhere


def test_only_confirmed_boxes_mark_gaussians():
    # box 0 isn't confirmed, so candidate 2 (inside box 0 only, shown only in view 0) isn't marked
    chosen = select(lifted(SEEN, HIT, GAP), BOXES, [0, 1], {"scratch": [0, 1]}, confirmed=[1])
    assert chosen["scratch"].tolist() == [True, False, False, False]


def test_red_share_per_view():
    lift = lifted(SEEN, HIT, GAP, item_px=(100.0, 50.0))
    assert red_shares(lift, np.array([True, False, True, False])) == pytest.approx([0.2, 0.2])


def png(img: PILImage.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def item_image(size=64, offset=0):
    img = PILImage.new("RGB", (size, size), (128, 128, 128))
    ImageDraw.Draw(img).rectangle([16 + offset, 16, 47 + offset, 47], fill=(30, 30, 30))
    return img


def test_camera_diff_is_zero_for_the_same_view_and_large_for_another():
    stored = png(item_image(64))
    assert camera_diff(stored, png(item_image(32 * 2).resize((32, 32), PILImage.Resampling.BOX)), 32,
                       (128, 128, 128)) == pytest.approx(0.0)
    moved = png(item_image(64, offset=12).resize((32, 32), PILImage.Resampling.BOX))
    assert camera_diff(stored, moved, 32, (128, 128, 128)) > HIGHLIGHT["camera_check_max_diff"]


# --- the whole stage, faked -------------------------------------------------------------------

SETTINGS = HIGHLIGHT | {"lift_px": 32, "min_gaussians_per_mark": 1}
SCRATCH = Defect(kind="scratch", score=0.8, view_ids=["v00"])
BASELINE = Baseline(query="q", image_path=None, source="image_search")


@pytest.fixture
def scene(tmp_path):
    """One stored 64 px view and a 10-Gaussian PLY; the fake lift says Gaussians 3 and 4 sit inside the box."""
    view_path = tmp_path / "v00.png"
    item_image(64).save(view_path)
    splat = tmp_path / "splat.ply"
    splat.write_bytes(ply_bytes(gaussians(np.arange(10.0), np.zeros(10), np.zeros(10))))
    views = Views(item_id="t", views=[View(view_id="v00", label="front, 10° above", azimuth_deg=0,
                                           elevation_deg=10, image_path=str(view_path))])
    return tmp_path, splat, views


def fake_lift(mask_item_px=20.0, seen_selected=10.0, stored_offset=0):
    def lift(data, up_axis, angles, masks, size):
        image = item_image(64, offset=stored_offset).resize((size, size), PILImage.Resampling.BOX)
        return {"gaussians": 10, "rendered": 100, "ids": np.array([2, 3, 4]),
                "seen": np.array([[10.0, seen_selected, seen_selected]]),
                "hit": np.array([[0.0, seen_selected, seen_selected]]),
                "depth_gap": np.zeros((1, 3)), "item_px": np.array([1000.0]),
                "mask_item_px": np.array([mask_item_px] * len(masks)), "images": [png(image)]}
    return lift


def patch(monkeypatch, boxes=((300, 300, 500, 500),), lift=None, calls=None):
    async def locate(views, targets, baseline_path, t):
        if calls is not None:
            calls.append([v.view_id for v in views])
        return {v.view_id: [DefectBox(kind="scratch", box_2d=list(b)) for b in boxes] for v in views}, {"raw": "fake"}

    monkeypatch.setattr(hl, "locate", locate)
    monkeypatch.setattr(hl, "lift_masks", lift or fake_lift())
    monkeypatch.setattr(hl, "render_pngs", lambda data, up, angles: [png(item_image(64))] * len(angles))


def run(scene, defects=(SCRATCH,)):
    out, splat, views = scene
    return asyncio.run(hl.make_highlight(splat, "+y", views, BASELINE, list(defects), out / "run", SETTINGS))


def test_stage_writes_a_tinted_copy_and_a_debug_sheet(scene, monkeypatch):
    patch(monkeypatch)
    result = run(scene)
    run_dir = scene[0] / "run"
    assert result.produced
    assert result.splat_path.endswith("splat_highlighted.ply")
    out = (run_dir / "splat_highlighted.ply").read_bytes()
    assert out != scene[1].read_bytes() and len(out) == len(scene[1].read_bytes())
    assert [(m.kind, m.view_ids, m.gaussian_count) for m in result.marks] == [("scratch", ["v00"], 2)]
    assert result.gaussian_share == pytest.approx(0.02)
    assert result.summary == "Marked scratches or scuffs (front, 10° above) in red: 2 of 100 Gaussians (2.0%)."
    assert (run_dir / "highlight_sheet.png").is_file() and (run_dir / "highlight" / "v00.png").is_file()
    raw = json.loads((run_dir / "highlight_raw.json").read_text(encoding="utf-8"))
    assert raw["boxes"][0]["status"] == "used" and raw["views"]["v00"]["camera_diff"] == 0.0
    assert (run_dir / "highlight" / "v00_highlighted.png").is_file()


def test_debug_render_failure_keeps_the_highlight(scene, monkeypatch):
    patch(monkeypatch)

    def offline(data, up, angles):
        raise ConnectionError("DNS lookup failed")

    monkeypatch.setattr(hl, "render_pngs", offline)
    result = run(scene)
    assert result.produced and (scene[0] / "run" / "highlight_sheet.png").is_file()
    raw = json.loads((scene[0] / "run" / "highlight_raw.json").read_text(encoding="utf-8"))
    assert "DNS lookup failed" in raw["debug_render_error"]


def test_no_noted_defects_skips_without_asking(scene, monkeypatch):
    calls = []
    patch(monkeypatch, calls=calls)
    result = run(scene, defects=())
    assert not result.produced and "no defects were noted" in result.summary
    assert calls == []


def test_defect_without_a_view_is_reported(scene, monkeypatch):
    patch(monkeypatch)
    result = run(scene, defects=(Defect(kind="stain", score=0.7, view_ids=[]),))
    assert not result.produced and "no single view clearly shows" in result.summary


def test_nothing_located_skips(scene, monkeypatch):
    patch(monkeypatch, boxes=())
    result = run(scene)
    assert not result.produced and "couldn't be located in any view" in result.summary


def test_too_broad_box_skips(scene, monkeypatch):
    patch(monkeypatch, lift=fake_lift(mask_item_px=600.0))  # 60% of the item's 1000 px
    result = run(scene)
    assert not result.produced
    assert "spread too widely to point at" in result.summary
    assert result.debug_sheet is not None  # the boxes are still drawn, for checking why


def test_too_much_red_skips(scene, monkeypatch):
    patch(monkeypatch, lift=fake_lift(seen_selected=150.0))  # 300 of 1000 px would turn red
    result = run(scene)
    assert not result.produced
    assert "30% of the item in the front, 10° above view" in result.summary
    assert "localisation probably went wrong" in result.summary
    assert not (scene[0] / "run" / "splat_highlighted.ply").exists()


def test_too_many_gaussians_skips(scene, monkeypatch):
    patch(monkeypatch)
    result = asyncio.run(hl.make_highlight(scene[1], "+y", scene[2], BASELINE, [SCRATCH], scene[0] / "run",
                                           SETTINGS | {"max_gaussian_share": 0.01}))
    assert not result.produced and "2% of the item's Gaussians" in result.summary


def test_views_from_other_cameras_skip(scene, monkeypatch):
    patch(monkeypatch, lift=fake_lift(stored_offset=14))
    result = run(scene)
    assert not result.produced and "doesn't match this splat's cameras" in result.summary


def test_locate_asks_once_for_all_views(tmp_path, monkeypatch):
    from gemini import GeminiReply

    views = []
    for i in range(2):
        item_image(64).save(tmp_path / f"v0{i}.png")
        views.append(View(view_id=f"v0{i}", label=f"view {i}", azimuth_deg=0, elevation_deg=10,
                          image_path=str(tmp_path / f"v0{i}.png")))
    calls = []

    async def fake(contents, system_prompt, schema, **kwargs):
        calls.append(schema)
        return GeminiReply(raw={"v00": [{"kind": "scratch", "box_2d": [1, 2, 30, 40]},
                                        {"kind": "crack", "box_2d": [1, 2, 30, 40]}]},  # v01 missing
                           model="fake", latency_ms=1.0)

    monkeypatch.setattr(hl, "generate_json", fake)
    found, record = asyncio.run(hl.locate(views, {"v00": ["scratch"], "v01": ["scratch", "crack"]}, None))
    assert len(calls) == 1
    props = calls[0]["properties"]
    assert props["v00"]["items"]["properties"]["kind"]["enum"] == ["scratch"]
    assert props["v01"]["items"]["properties"]["kind"]["enum"] == ["scratch", "crack"]
    assert [b.box_2d for b in found["v00"]] == [[1, 2, 30, 40]] and found["v01"] == []
    assert record["dropped"]["v00"][0]["reason"] == "crack was not asked for in this view"


def test_gemini_failing_raises(scene, monkeypatch):
    patch(monkeypatch)

    async def down(views, targets, baseline_path, t):
        raise RuntimeError("Gemini is down")

    monkeypatch.setattr(hl, "locate", down)
    with pytest.raises(RuntimeError, match="Gemini is down"):
        run(scene)
    raw = json.loads((scene[0] / "run" / "highlight_raw.json").read_text(encoding="utf-8"))
    assert "Gemini is down" in raw["error"]
