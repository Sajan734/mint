"""highlight: splat + views + baseline + condition -> Highlight, and a copy of the splat with the noted defects red.

Fixture items that have stubs/highlight.json stay offline. Otherwise, for the defects finalize notes for buyers:
  1. locate: one Gemini call with every view that shows a noted defect (Defect.view_ids) and the baseline photo
     when there is one -> per view, a tight box around each visible mark (DefectBox, Gemini's 0-1000 box format)
  2. lift: splat_render.lift_masks on the RENDER_BACKEND with the render stage's cameras -> how much of each
     Gaussian shows inside each box's inscribed ellipse, and whether it lies on the visible surface or behind it
  3. select (code): a box counts only if the other views searched for its kind box most of what they see of it
     (or see too little of it to say), so a box on a logo that another view sees and leaves alone is dropped. A
     Gaussian is marked when most of its visible footprint is inside a counted box, and inside that kind's boxes in
     at least vote_min of the searched views that show it; Gaussians hidden behind the surface never count
  4. check (code): the lift must reproduce the stored views (same cameras), no box may cover too much of the item,
     and the marks may not cover too much of it either; otherwise nothing is written and the summary says why
  5. write: splat_render.tint_splat on a copy of the original .spz/.ply -> <out>/splat_highlighted.<ext>
Debug: <out>/highlight/<view>.png (the view with its boxes | the highlighted splat from the same camera; boxes in
yellow were used, orange weren't confirmed, grey were too broad), <out>/highlight/<view>_highlighted.png (full size),
<out>/highlight_sheet.png, and <out>/highlight_raw.json (Gemini's answers, box statuses, counts, timings).
The pipeline runs this stage isolated: any error becomes a Highlight with produced=False and the listing goes on.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image as PILImage, ImageDraw, ImageFont
from pydantic import ValidationError

from contracts import Baseline, Condition, Defect, DefectBox, Highlight, HighlightMark, RunContext, View, Views
from gemini import contract_schema, generate_json
from stages._fixture import has_stub, load_stub
from stages.finalize import DEFECT_NOUNS, join_words, noted_defects
from stages.identify import load_image, resolve
from stages.render import RENDER, _relative, lift_masks, render_pngs

GZIP_MAGIC = b"\x1f\x8b"  # an .spz; anything else is a .ply

HIGHLIGHT = {
    "lift_px": 512,  # lifting resolution: the render stage's cameras, scaled from its 1024 px views
    "max_boxes_per_view": 4,
    "min_box_side": 0.03,  # boxes are widened to at least this share of the view, so tiny marks cover whole Gaussians
    "max_box_item_share": 0.30,  # a box covering more of the item than this in its view is too broad to point at
    "seen_min_px": 0.05,  # blending weight (pixels at lift_px) for a Gaussian to count as showing in a view
    "surface_gap_max": 0.05,  # framing radii behind the rendered surface; deeper Gaussians are hidden in that view
    "share_min": 0.60,  # share of a Gaussian's visible footprint inside a kind's ellipses to mark it in a view
    "confirm_min": 0.50,  # a box counts when other views searched for its kind mark this share of what they see of it
    "confirm_min_checked": 10,  # fewer of its Gaussians seen by other views is no evidence either way
    "vote_min": 0.60,  # marked in at least this share of the views searched for the kind that show it
    "min_gaussians_per_mark": 8,  # fewer marked Gaussians for a kind is noise, not a mark
    "max_gaussian_share": 0.05,  # of the item's rendered Gaussians; more means localisation went wrong
    "max_view_red_share": 0.20,  # of the item's pixels in any searched view; more means localisation went wrong
    "camera_check_max_diff": 20.0,  # mean abs RGB difference (0-255) over item pixels, lift render vs stored view
    "camera_check_item_diff": 8,  # a pixel is an item pixel when it differs from the background by more than this
    "tint_rgb": (1.0, 0.08, 0.08),
    "tint_strength": 0.85,
    "debug_render": True,  # re-render the highlighted splat from each searched view for the debug sheet
}

SHEET = {
    "thumb_px": 512,
    "caption_px": 34,
    "font_px": 18,
    "line_px": 3,
    "box_rgb": {  # by box status
        "used": (255, 214, 0),
        "not confirmed": (255, 128, 0),
        "too broad": (170, 170, 170),
    },
    "background_rgb": (32, 32, 32),
}

SYSTEM_PROMPT = """\
You point at known defects on a used item. You get renders of a 3D scan (Gaussian splat) of the item, each from \
a different side on a grey background and each preceded by its view id, and sometimes `baseline`, a photo of the \
same product new, to tell damage from design.

For each view, draw one tight box around each separate visible mark of the defects you are asked about in that \
view, on the item in that render.
- Box only physical damage that the intact product doesn't have. Never box logos, printed text, buttons, wheels, \
seams, vents, coloured design parts (compare with `baseline` when given), shadows, reflections or highlights, or \
scan artifacts: soft or fuzzy edges, floaters, speckle, holes, smeared texture.
- Keep each box tight around its mark. Separate marks get separate boxes, at most {max_boxes} per view.
- If no such mark is clearly visible on the item in a view, give that view an empty list.
- box_2d is [ymin, xmin, ymax, xmax] on that view's render, each scaled from 0 to 1000.\
"""


def not_produced(reason: str) -> Highlight:
    return Highlight(produced=False, summary=f"No highlighted splat: {reason.rstrip('.')}.")


@dataclass(frozen=True)
class Box:
    """A located mark as fractions (0..1) of its view, widened to the minimum size. `view` indexes searched views."""

    view: int
    kind: str
    top: float
    left: float
    bottom: float
    right: float

    @classmethod
    def of(cls, view: int, box: DefectBox, min_side: float) -> Box:
        ymin, xmin, ymax, xmax = (c / 1000 for c in box.box_2d)
        top, bottom = widen(ymin, ymax, min_side)
        left, right = widen(xmin, xmax, min_side)
        return cls(view, box.kind, top, left, bottom, right)


@dataclass(frozen=True)
class Lifted:
    """splat_render.lift_masks' result. C candidate Gaussians, V searched views, M boxes (rows in `hit`)."""

    gaussians: int
    rendered: int
    ids: np.ndarray  # (C,) file indices
    seen: np.ndarray  # (V, C)
    hit: np.ndarray  # (M, C)
    depth_gap: np.ndarray  # (V, C)
    item_px: np.ndarray  # (V,)
    mask_item_px: np.ndarray  # (M,)
    images: list[bytes] = field(default_factory=list)

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Lifted:
        arrays = ("ids", "seen", "hit", "depth_gap", "item_px", "mask_item_px")
        return cls(int(raw["gaussians"]), int(raw["rendered"]), *(np.asarray(raw[a]) for a in arrays),
                   images=list(raw["images"]))


# --- boxes and masks (pure) -------------------------------------------------------------------


def widen(lo: float, hi: float, min_side: float) -> tuple[float, float]:
    """The span grown around its middle to at least min_side, kept inside 0..1."""
    if hi - lo >= min_side:
        return lo, hi
    mid = (lo + hi) / 2
    lo, hi = mid - min_side / 2, mid + min_side / 2
    shift = max(0.0 - lo, 0.0) - max(hi - 1.0, 0.0)
    return lo + shift, hi + shift


def ellipse_mask(box: Box, size: int) -> np.ndarray:
    """(size, size) uint8: 255 inside the ellipse inscribed in the box, 0 outside."""
    centres = (np.arange(size) + 0.5) / size
    cy, cx = (box.top + box.bottom) / 2, (box.left + box.right) / 2
    ry, rx = (box.bottom - box.top) / 2, (box.right - box.left) / 2
    inside = ((centres[None, :] - cx) / rx) ** 2 + ((centres[:, None] - cy) / ry) ** 2 <= 1.0
    return inside.astype(np.uint8) * 255


def kinds_by_view(defects: list[Defect], views: Views) -> dict[str, list[str]]:
    """{view_id: defect kinds condition saw in it}, in render order."""
    found: dict[str, list[str]] = {}
    for d in defects:
        for view_id in d.view_ids:
            kinds = found.setdefault(view_id, [])
            if d.kind not in kinds:
                kinds.append(d.kind)
    return {v.view_id: found[v.view_id] for v in views.views if v.view_id in found}


def boxes_schema(kinds: list[str]) -> dict[str, Any]:
    """DefectBox's schema for Gemini, with kind narrowed to what was asked for this view."""
    box = contract_schema(DefectBox, ["kind", "box_2d"])
    box["properties"]["kind"] = {"type": "string", "enum": list(kinds)}
    return {"type": "object", "properties": {"boxes": {"type": "array", "items": box}}, "required": ["boxes"]}


def parse_boxes(raw: dict[str, Any], kinds: list[str], max_boxes: int) -> tuple[list[DefectBox], list[dict]]:
    """Gemini's answer -> (valid boxes of the asked kinds, dropped answers with the reason). Never raises."""
    boxes: list[DefectBox] = []
    dropped: list[dict] = []
    for answer in raw.get("boxes") or []:
        try:
            box = DefectBox.model_validate(answer)
        except ValidationError as e:
            dropped.append({"answer": answer, "reason": f"invalid: {e.errors()[0]['msg']}"})
            continue
        if box.kind not in kinds:
            dropped.append({"answer": answer, "reason": f"{box.kind} was not asked for in this view"})
        elif len(boxes) >= max_boxes:
            dropped.append({"answer": answer, "reason": f"over the {max_boxes}-box limit"})
        else:
            boxes.append(box)
    return boxes, dropped


# --- selection and checks (pure) --------------------------------------------------------------


def visible(lifted: Lifted, t: dict[str, Any] = HIGHLIGHT) -> np.ndarray:
    """(V, C) bool: the candidate shows in the view and lies on the rendered surface, not behind it."""
    return (lifted.seen >= t["seen_min_px"]) & (lifted.depth_gap <= t["surface_gap_max"])


def inside_share(lifted: Lifted, rows: list[int], view: int) -> np.ndarray:
    """(C,) share of each candidate's weight in the view that falls inside the given boxes (rows of hit)."""
    if not rows:
        return np.zeros(lifted.seen.shape[1])
    return lifted.hit[rows].sum(0) / np.maximum(lifted.seen[view], 1e-9)


def kind_rows(boxes: list[Box], kept: list[int], kind: str, view: int) -> list[int]:
    return [m for m in kept if boxes[m].kind == kind and boxes[m].view == view]


def marked_in(lifted: Lifted, boxes: list[Box], kept: list[int], kind: str, view: int,
              t: dict[str, Any] = HIGHLIGHT) -> np.ndarray:
    """(C,) bool: visible in the view and mostly inside the kind's kept boxes there."""
    rows = kind_rows(boxes, kept, kind, view)
    return visible(lifted, t)[view] & (inside_share(lifted, rows, view) >= t["share_min"])


def corroboration(lifted: Lifted, boxes: list[Box], kept: list[int], m: int, views: list[int],
                  t: dict[str, Any] = HIGHLIGHT) -> float | None:
    """Of the Gaussians box m marks in its view, the share that the other views searched for its kind also mark,
    among those they show. None when they show fewer than confirm_min_checked of them: no evidence either way."""
    box = boxes[m]
    shows = visible(lifted, t)
    own = shows[box.view] & (inside_share(lifted, [m], box.view) >= t["share_min"])
    checked = agreed = 0
    for w in views:
        if w != box.view:
            seen_there = own & shows[w]
            checked += int(seen_there.sum())
            agreed += int((seen_there & marked_in(lifted, boxes, kept, box.kind, w, t)).sum())
    return None if checked < t["confirm_min_checked"] else agreed / checked


def confirmed_boxes(lifted: Lifted, boxes: list[Box], kept: list[int], searched: dict[str, list[int]],
                    t: dict[str, Any] = HIGHLIGHT) -> tuple[list[int], dict[int, float | None]]:
    """Returns (the kept boxes other views don't contradict, each kept box's corroboration). A box on something
    the other views see and don't box, such as a logo seen edge-on in one view, is dropped whole."""
    rates = {m: corroboration(lifted, boxes, kept, m, searched.get(boxes[m].kind, []), t) for m in kept}
    return [m for m, rate in rates.items() if rate is None or rate >= t["confirm_min"]], rates


def select(lifted: Lifted, boxes: list[Box], kept: list[int], searched: dict[str, list[int]],
           t: dict[str, Any] = HIGHLIGHT, confirmed: list[int] | None = None) -> dict[str, np.ndarray]:
    """{kind: (C,) bool}: inside a confirmed box in some view, and marked (by any kept box) in at least vote_min
    of the views searched for the kind that show it. A view that wasn't searched for a kind never counts for or
    against it."""
    confirmed = kept if confirmed is None else confirmed
    shows = visible(lifted, t)
    chosen = {}
    for kind, views in searched.items():
        marked = np.zeros(lifted.seen.shape[1], dtype=int)
        shown = np.zeros(lifted.seen.shape[1], dtype=int)
        in_confirmed = np.zeros(lifted.seen.shape[1], dtype=bool)
        for v in views:
            shown += shows[v]
            marked += marked_in(lifted, boxes, kept, kind, v, t)
            in_confirmed |= marked_in(lifted, boxes, confirmed, kind, v, t)
        chosen[kind] = in_confirmed & (marked >= t["vote_min"] * shown)
    return chosen


def red_shares(lifted: Lifted, selected: np.ndarray) -> list[float]:
    """Per searched view, the share of the item's pixels the selected Gaussians cover."""
    return [float(lifted.seen[v, selected].sum() / max(float(lifted.item_px[v]), 1e-9))
            for v in range(len(lifted.item_px))]


def camera_diff(stored_png: bytes, lifted_png: bytes, size: int, background_rgb: tuple[int, int, int],
                t: dict[str, Any] = HIGHLIGHT) -> float:
    """Mean abs RGB difference over item pixels between a stored view (downsampled) and the lift's render of it."""
    with PILImage.open(io.BytesIO(stored_png)) as img:
        stored = np.asarray(img.convert("RGB").resize((size, size), PILImage.Resampling.BOX), dtype=np.float32)
    with PILImage.open(io.BytesIO(lifted_png)) as img:
        lifted = np.asarray(img.convert("RGB"), dtype=np.float32)
    background = np.asarray(background_rgb, dtype=np.float32)
    item = ((np.abs(stored - background).max(2) > t["camera_check_item_diff"])
            | (np.abs(lifted - background).max(2) > t["camera_check_item_diff"]))
    return float(np.abs(stored - lifted).max(2)[item].mean()) if item.any() else 0.0


def summarize(marks: list[HighlightMark], labels: dict[str, str], selected: int, rendered: int,
              unmarked: dict[str, str]) -> str:
    parts = [f"{DEFECT_NOUNS[m.kind]} ({'; '.join(labels[v] for v in m.view_ids)})" for m in marks]
    text = (f"Marked {join_words(parts)} in red: {selected:,} of {rendered:,} Gaussians "
            f"({selected / rendered:.1%}).")
    if unmarked:
        text += f" Not marked: {join_words([f'{DEFECT_NOUNS[k]} ({why})' for k, why in unmarked.items()])}."
    return text


# --- Gemini -----------------------------------------------------------------------------------


async def locate(views: list[View], targets: dict[str, list[str]], baseline_path: str | None,
                 t: dict[str, Any] = HIGHLIGHT) -> tuple[dict[str, list[DefectBox]], dict[str, Any]]:
    """One Gemini call for all the views (the key's daily request quota is small): boxes around the visible marks
    of the kinds in targets[view_id], per view. Returns ({view_id: boxes}, a record for the raw log)."""
    from google.genai import types

    parts: list[Any] = []
    for view in views:
        data, mime, _ = load_image(resolve(view.image_path))
        parts += [types.Part.from_text(text=f"View {view.view_id}:"), types.Part.from_bytes(data=data, mime_type=mime)]
    if baseline_path:
        photo, photo_mime, _ = load_image(resolve(baseline_path))
        parts += [types.Part.from_text(text="`baseline`:"), types.Part.from_bytes(data=photo, mime_type=photo_mime)]
    asks = [f"View {v.view_id}: a condition check found {join_words([DEFECT_NOUNS[k] for k in targets[v.view_id]])} "
            f"there ({'; '.join(f'kind {k!r} for {DEFECT_NOUNS[k]}' for k in targets[v.view_id])})." for v in views]
    parts.append(types.Part.from_text(text="Box each visible mark.\n" + "\n".join(asks)))
    schema = {"type": "object", "properties": {v.view_id: boxes_schema(targets[v.view_id])["properties"]["boxes"]
                                               for v in views}, "required": [v.view_id for v in views]}
    reply = await generate_json(parts, SYSTEM_PROMPT.format(max_boxes=t["max_boxes_per_view"]), schema)
    found, dropped = {}, {}
    for view in views:
        found[view.view_id], dropped[view.view_id] = parse_boxes(
            {"boxes": reply.raw.get(view.view_id)}, targets[view.view_id], t["max_boxes_per_view"]
        )
    return found, {"model": reply.model, "latency_ms": round(reply.latency_ms), "raw": reply.raw, "dropped": dropped}


# --- debug sheet ------------------------------------------------------------------------------


def box_overlay(view: View, boxes: list[tuple[Box, str]]) -> PILImage.Image:
    """The stored view with each box and its ellipse drawn, coloured and labelled by status (SHEET["box_rgb"])."""
    with PILImage.open(resolve(view.image_path)) as img:
        out = img.convert("RGB")
    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default(size=SHEET["font_px"] * 2)
    w, h = out.size
    for box, status in boxes:
        colour = SHEET["box_rgb"][status]
        xy = [box.left * w, box.top * h, box.right * w, box.bottom * h]
        draw.rectangle(xy, outline=colour, width=SHEET["line_px"])
        draw.ellipse(xy, outline=colour, width=SHEET["line_px"] - 1)
        label = box.kind if status == "used" else f"{box.kind} ({status})"
        draw.text((xy[0] + 4, max(0.0, xy[1] - SHEET["font_px"] * 2 - 6)), label, fill=colour, font=font)
    return out


def debug_panel(view: View, left: PILImage.Image, right_png: bytes | None, caption: str) -> PILImage.Image:
    thumb, cap = SHEET["thumb_px"], SHEET["caption_px"]
    panel = PILImage.new("RGB", (2 * thumb, thumb + cap), SHEET["background_rgb"])
    panel.paste(left.resize((thumb, thumb)), (0, 0))
    draw = ImageDraw.Draw(panel)
    font = ImageFont.load_default(size=SHEET["font_px"])
    if right_png is not None:
        with PILImage.open(io.BytesIO(right_png)) as img:
            panel.paste(img.convert("RGB").resize((thumb, thumb)), (thumb, 0))
    else:
        draw.text((thumb + 16, thumb // 2), "no highlighted splat", fill=(235, 235, 235), font=font)
    draw.text((8, thumb + 6), f"{view.view_id}  {view.label}  {caption}", fill=(235, 235, 235), font=font)
    return panel


def write_debug(out_dir: Path, views: list[View], boxes: list[Box], status: dict[int, str],
                renders: list[bytes] | None, captions: list[str]) -> Path:
    """<out>/highlight/<view>.png per searched view (and <view>_highlighted.png, the full-size render of the
    highlighted splat, for zooming in), and <out>/highlight_sheet.png stacking the panels."""
    folder = out_dir / "highlight"
    folder.mkdir(parents=True, exist_ok=True)
    panels = []
    for v, view in enumerate(views):
        mine = [(b, status.get(m, "used")) for m, b in enumerate(boxes) if b.view == v]
        panel = debug_panel(view, box_overlay(view, mine), renders[v] if renders else None, captions[v])
        panel.save(folder / f"{view.view_id}.png")
        if renders:
            (folder / f"{view.view_id}_highlighted.png").write_bytes(renders[v])
        panels.append(panel)
    sheet = PILImage.new("RGB", (panels[0].width, sum(p.height for p in panels)), SHEET["background_rgb"])
    for i, panel in enumerate(panels):
        sheet.paste(panel, (0, i * panel.height))
    path = out_dir / "highlight_sheet.png"
    sheet.save(path)
    return path


# --- the stage --------------------------------------------------------------------------------


@dataclass
class Debug:
    """What the debug sheet needs, filled in as the run gets that far."""

    views: list[View] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)
    status: dict[int, str] = field(default_factory=dict)  # box index -> "too broad" / "not confirmed"; else used
    renders: list[bytes] | None = None
    captions: list[str] = field(default_factory=list)


async def make_highlight(splat_path: Path, up_axis: str, views: Views, baseline: Baseline, defects: list[Defect],
                         out_dir: Path, t: dict[str, Any] = HIGHLIGHT) -> Highlight:
    """Highlights `defects` on a copy of the splat in out_dir. Raises on errors; skips (produced=False) on purpose."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log: dict[str, Any] = {"thresholds": t, "defects": [d.model_dump() for d in defects], "views": {},
                           "timings_ms": {}}
    debug = Debug()
    try:
        result = await _highlight(splat_path, up_axis, views, baseline, defects, out_dir, t, log, debug)
        if debug.views:
            sheet = write_debug(out_dir, debug.views, debug.boxes, debug.status, debug.renders,
                                debug.captions or [""] * len(debug.views))
            result = result.model_copy(update={"debug_sheet": _relative(sheet)})
        log["summary"] = result.summary
        return result
    except Exception as e:
        log["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        (out_dir / "highlight_raw.json").write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")


async def _highlight(splat_path: Path, up_axis: str, views: Views, baseline: Baseline, defects: list[Defect],
                     out_dir: Path, t: dict[str, Any], log: dict[str, Any], debug: Debug) -> Highlight:
    if not defects:
        return not_produced("no defects were noted, so there is nothing to mark")
    labels = {v.view_id: v.label for v in views.views}
    order = list(dict.fromkeys(d.kind for d in defects))
    unmarked = {d.kind: "no single view shows it clearly" for d in defects if not d.view_ids}
    targets = kinds_by_view(defects, views)
    if not targets:
        return not_produced(f"no single view clearly shows the noted {join_words([DEFECT_NOUNS[k] for k in order])}")

    # 1. locate
    start = time.perf_counter()
    target_views = [v for v in views.views if v.view_id in targets]
    found, log["gemini"] = await locate(target_views, targets, baseline.image_path, t)
    log["timings_ms"]["locate"] = round((time.perf_counter() - start) * 1000)
    searched: dict[str, list[int]] = {}
    for v, view in enumerate(target_views):
        log["views"][view.view_id] = {"kinds": targets[view.view_id]}
        debug.views.append(view)
        for kind in targets[view.view_id]:
            searched.setdefault(kind, []).append(v)
        debug.boxes += [Box.of(v, b, t["min_box_side"]) for b in found[view.view_id]]
    for kind in order:
        if kind not in unmarked and not any(b.kind == kind for b in debug.boxes):
            unmarked[kind] = "not found in the views that show it"
    if not debug.boxes:
        return not_produced(f"the noted {join_words([DEFECT_NOUNS[k] for k in order])} couldn't be located in any view")

    # 2. lift
    start = time.perf_counter()
    data = splat_path.read_bytes()
    size = t["lift_px"]
    angles = [(v.azimuth_deg, v.elevation_deg) for v in debug.views]
    masks = [(b.view, ellipse_mask(b, size)) for b in debug.boxes]
    lifted = Lifted.of(await asyncio.to_thread(lift_masks, data, up_axis, angles, masks, size))
    log["timings_ms"]["lift"] = round((time.perf_counter() - start) * 1000)
    log |= {"gaussians": lifted.gaussians, "rendered": lifted.rendered, "candidates": len(lifted.ids)}

    # 3. checks before selecting: same cameras, and boxes that point at something
    for v, view in enumerate(debug.views):
        diff = camera_diff(resolve(view.image_path).read_bytes(), lifted.images[v], size, RENDER["background_rgb"], t)
        log["views"][view.view_id] |= {"camera_diff": round(diff, 2), "item_px": float(lifted.item_px[v])}
        if diff > t["camera_check_max_diff"]:
            return not_produced(
                f"the stored {view.view_id} view doesn't match this splat's cameras (mean difference {diff:.1f}, "
                f"limit {t['camera_check_max_diff']:.0f}); re-render the views"
            )
    log["boxes"] = []
    for m, box in enumerate(debug.boxes):
        share = float(lifted.mask_item_px[m] / max(float(lifted.item_px[box.view]), 1e-9))
        log["boxes"].append({"view_id": debug.views[box.view].view_id, "kind": box.kind,
                             "box": [round(c, 4) for c in (box.top, box.left, box.bottom, box.right)],
                             "item_share": round(share, 4)})
        if share > t["max_box_item_share"]:
            debug.status[m] = "too broad"
            if box.view in searched.get(box.kind, []):
                searched[box.kind].remove(box.view)  # a too-broad box isn't evidence for or against anything there
    broad_views = {(debug.boxes[m].kind, debug.boxes[m].view) for m in debug.status}
    for m, box in enumerate(debug.boxes):  # the other boxes of that kind in that view go with it
        if (box.kind, box.view) in broad_views:
            debug.status[m] = "too broad"
    kept = [m for m in range(len(debug.boxes)) if m not in debug.status]

    # 4. select: boxes the other views don't contradict, then the Gaussians the views agree on
    confirmed, rates = confirmed_boxes(lifted, debug.boxes, kept, searched, t)
    for m in kept:
        log["boxes"][m]["corroboration"] = None if rates[m] is None else round(rates[m], 3)
        if m not in confirmed:
            debug.status[m] = "not confirmed"
    for m, entry in enumerate(log["boxes"]):
        entry["status"] = debug.status.get(m, "used")
    chosen = select(lifted, debug.boxes, kept, searched, t, confirmed)
    marks: list[HighlightMark] = []
    selected = np.zeros(len(lifted.ids), dtype=bool)
    for kind in order:
        if kind in unmarked:
            continue
        if not any(debug.boxes[m].kind == kind for m in kept):
            unmarked[kind] = "spread too widely to point at"
            continue
        if not any(debug.boxes[m].kind == kind for m in confirmed):
            unmarked[kind] = "the other views that show the spot didn't confirm it"
            continue
        sel = chosen[kind]
        count = int(sel.sum())
        if count == 0:
            unmarked[kind] = "its boxes didn't line up with the scan's surface in the views that show it"
            continue
        if count < t["min_gaussians_per_mark"]:
            unmarked[kind] = "too small to mark"
            continue
        in_views = [debug.views[v].view_id for v in searched[kind]
                    if (marked_in(lifted, debug.boxes, confirmed, kind, v, t) & sel).any()]
        marks.append(HighlightMark(kind=kind, view_ids=in_views, gaussian_count=count))
        selected |= sel
    log["unmarked"] = unmarked
    log["marks"] = [m.model_dump() for m in marks]
    n_selected = int(selected.sum())
    shares = red_shares(lifted, selected)
    debug.captions = [f"red covers {s:.1%} of the item" for s in shares]
    for v, view in enumerate(debug.views):
        log["views"][view.view_id]["red_share"] = round(shares[v], 4)
    if not marks:
        reasons = join_words([f"{DEFECT_NOUNS[k]} ({why})" for k, why in unmarked.items()])
        return not_produced(f"none of the noted defects could be pinned to the scan: {reasons}")

    # 5. sanity checks on the whole highlight
    gaussian_share = n_selected / lifted.rendered
    if gaussian_share > t["max_gaussian_share"]:
        return not_produced(
            f"the marks would turn {gaussian_share:.0%} of the item's Gaussians red (limit "
            f"{t['max_gaussian_share']:.0%}), so localisation probably went wrong"
        )
    worst = int(np.argmax(shares))
    if shares[worst] > t["max_view_red_share"]:
        return not_produced(
            f"the marks would cover {shares[worst]:.0%} of the item in the {debug.views[worst].label} view (limit "
            f"{t['max_view_red_share']:.0%}), so localisation probably went wrong"
        )

    # 6. write the tinted copy, and render it from the searched views for the debug sheet
    from splat_render import tint_splat  # imports torch, so only once there is something to write

    start = time.perf_counter()
    tinted = tint_splat(data, lifted.ids[selected], t["tint_rgb"], t["tint_strength"])
    suffix = ".spz" if data[:2] == GZIP_MAGIC else ".ply"
    out = out_dir / f"splat_highlighted{suffix}"
    out.write_bytes(tinted)
    log["timings_ms"]["write"] = round((time.perf_counter() - start) * 1000)
    if t["debug_render"]:
        start = time.perf_counter()
        try:
            debug.renders = await asyncio.to_thread(render_pngs, tinted, up_axis, angles)
        except Exception as e:  # noqa: BLE001  debug only: the highlighted splat is already written
            log["debug_render_error"] = f"{type(e).__name__}: {e}"
        log["timings_ms"]["debug_render"] = round((time.perf_counter() - start) * 1000)
    return Highlight(
        produced=True,
        splat_path=_relative(out),
        summary=summarize(marks, labels, n_selected, lifted.rendered, unmarked),
        marks=marks,
        gaussian_share=round(gaussian_share, 5),
    )


async def highlight(ctx: RunContext, splat_path: Path, views: Views, baseline: Baseline,
                    condition: Condition) -> Highlight:
    if has_stub(ctx, "highlight"):
        return load_stub(ctx, "highlight", Highlight)
    return await make_highlight(Path(splat_path), ctx.up_axis, views, baseline, noted_defects(condition.defects),
                                ctx.run_dir)
