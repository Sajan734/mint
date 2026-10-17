"""Jev contexts and questions shared by the match_gate and condition stages and the smoke test.

Every request's state is {"context": <task context>, "baseline": Image, "item": Image}.
Every Noul is phrased so a high value means yes.
"""

from __future__ import annotations

from typing import Any

from typesafe_sdk import Image, Noul, NoulCriteria, Score

MODEL = "jev-latest"
IMAGE_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}

GATE_CONTEXT = (
    "`baseline` is a reference photo of a product. `item` is a render of a 3D scan of a used item that a "
    "seller says is that product. They are NOT taken from the same angle, and lighting, background and scale "
    "differ. The item may be worn, scratched, stained or dirty. None of that counts as a difference. Judge only "
    "whether it is the same product: overall shape, proportions, distinctive parts, logos, colour scheme and "
    "design details. A different colourway of the same model counts as the same product."
)

CONDITION_CONTEXT = (
    "`item` is a render of a 3D scan (Gaussian splat) of a used item being listed for resale. `baseline` shows "
    "the product new, from a different angle; use it to know what the intact product looks like. Judge the "
    "physical condition of the item. Ignore scan artifacts: soft, blurry or fuzzy edges; faint speckle, thin "
    "wisps and small scattered floaters; tiny pinholes; slightly smeared texture; lighting, exposure and "
    "reflections. A region the scan never covered looks ragged or hollow; treat that as an artifact unless a "
    "solid part is clearly broken. These ARE condition issues even when they look blurry: scratches or scuffs, "
    "stains or discolouration that isn't part of the design, cracks or tears, a broken or missing piece."
)

GATE_QUESTIONS = {
    "item_usable": Noul(
        instructions=(
            "Following `context`: does `item` show the object clearly enough to tell what product it is?"
        ),
        criteria=NoulCriteria(
            true=(
                "The object is in frame and its overall shape and main features can be made out, "
                "even if edges are soft or there are a few scan specks."
            ),
            false=(
                "The image is mostly empty, blur or noise, or shows only a tiny or cut-off fragment, "
                "so the product can't be recognised from it."
            ),
        ),
    ),
    "same_category": Noul(
        instructions=(
            "Following `context`: do `baseline` and `item` show the same kind of object "
            "(for example, both over-ear headphones, or both running shoes)?"
        ),
        criteria=NoulCriteria(
            true="Both are the same general type of object, even if their brand, model or colour differ.",
            false="They are different types of object, such as headphones and a speaker, or a mug and a vase.",
        ),
    ),
    "same_product": Noul(
        instructions=(
            "Following `context`: do `baseline` and `item` show the same product, with the same type, "
            "brand, model and design?"
        ),
        criteria=NoulCriteria(
            true=(
                "Overall shape, proportions, distinctive parts, logos and design details agree. A different "
                "angle, lighting, scale, colourway of the same model, or wear and dirt does not matter."
            ),
            false=(
                "At least one clear design difference shows a different model or brand: a different shape or "
                "proportions, distinctive parts that differ or are arranged differently, a different logo, or "
                "different design details."
            ),
        ),
    ),
}

WEAR_LEVELS = ["like_new", "light_wear", "moderate_wear", "heavy_wear"]  # Score levels 0..3, in order

CONDITION_QUESTIONS = {
    "item_usable": Noul(
        instructions=(
            "Following `context`: does `item` show enough of the object's surface, clearly enough, "
            "to judge its physical condition?"
        ),
        criteria=NoulCriteria(
            true=(
                "Most of the visible object is rendered solidly enough that a scratch, stain, crack or missing "
                "piece would be noticeable, even with soft edges or a few scan specks."
            ),
            false=(
                "The object is mostly blur, noise, or ragged or hollow scan, or is too small or cut off, so its "
                "condition can't be judged from this image."
            ),
        ),
    ),
    "scratches_scuffs": Noul(
        instructions="Following `context`: does the item in `item` have any scratches or scuffs?",
        criteria=NoulCriteria(
            true=(
                "At least one scratch, scuff, scrape or abrasion mark is visible on the item's surface, "
                "even a small or slightly blurry one."
            ),
            false=(
                "No scratches or scuffs. Soft edges, speckle, floaters, smeared texture and lighting changes "
                "are scan or lighting artifacts, not scratches."
            ),
        ),
    ),
    "stains_discolouration": Noul(
        instructions=(
            "Following `context`: does the item in `item` have any stains or discolouration that isn't part "
            "of the product's design, judged against the intact product in `baseline`?"
        ),
        criteria=NoulCriteria(
            true=(
                "A spot, patch or area has a colour that the intact product doesn't have and that isn't a "
                "printed pattern, logo, lighting or reflection: a stain, yellowing, fading or a dirt mark."
            ),
            false=(
                "The colours match the product's design apart from lighting, exposure and reflections. A whole "
                "product in a uniformly different colour is a different colourway, not discolouration."
            ),
        ),
    ),
    "cracks_tears": Noul(
        instructions="Following `context`: does the item in `item` have any cracks or tears?",
        criteria=NoulCriteria(
            true=(
                "A crack, split, tear or rip is visible in any material of the item, such as plastic, metal, "
                "leather, fabric or foam."
            ),
            false=(
                "No cracks or tears. Ragged or hollow areas where the scan didn't cover the surface are "
                "artifacts, not tears."
            ),
        ),
    ),
    "missing_broken": Noul(
        instructions=(
            "Following `context`: compared with the intact product in `baseline`, is any piece of the item in "
            "`item` broken or missing?"
        ),
        criteria=NoulCriteria(
            true=(
                "A part the intact product has, such as a button, cap, cushion, cover, strap or tip, is absent, "
                "snapped off or clearly broken, and the area around it is solidly scanned."
            ),
            false=(
                "Every part that can be seen from this angle is present and intact. Parts hidden by the angle "
                "and areas the scan never covered do not count as missing."
            ),
        ),
    ),
    "wear": Score(
        instructions="Following `context`: how worn is the item in `item` overall?",
        criteria=[
            "Like new: no visible marks, wear or damage; it looks as it did out of the box.",
            "Light wear: a few small marks or slight surface wear that only show on a close look; fully intact.",
            (
                "Moderate wear: several clearly visible scratches, scuffs or stains, or noticeable wear on edges, "
                "pads or grips; still intact and usable."
            ),
            (
                "Heavy wear: extensive or deep marks, heavy staining, cracks or tears, or a broken or "
                "missing part."
            ),
        ],
    ),
}

TASKS: dict[str, tuple[str, dict[str, Any]]] = {
    "gate": (GATE_CONTEXT, GATE_QUESTIONS),
    "condition": (CONDITION_CONTEXT, CONDITION_QUESTIONS),
}


def build_state(context: str, baseline: Image, item: Image) -> dict[str, Any]:
    return {"context": context, "baseline": baseline, "item": item}
