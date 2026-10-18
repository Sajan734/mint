"""Jev contexts and questions shared by the match_gate and condition stages and the smoke test.

Every request's state is {"context": <task context>, "baseline": Image, "item": Image}.
Every Noul is phrased so a high value means yes.
"""

from __future__ import annotations

from typing import Any

from typesafe_sdk import Image, Noul, NoulCriteria, Score

from contracts import Identity

MODEL = "jev-latest"
IMAGE_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}

GATE_CONTEXT = (
    "`baseline` is a reference photo of a product. `item` is a seller's photo of a used item (or a render of a "
    "3D scan of it) that the seller says is that product. They are NOT taken from the same angle, and lighting, "
    "background and scale differ. The item may be worn, scratched, stained or dirty. None of that counts as a difference. Judge only "
    "whether it is the same product: overall shape, proportions, distinctive parts, logos, colour scheme and "
    "design details. A different colourway of the same model counts as the same product."
)

CONDITION_CONTEXT = (
    "`item` is a seller's photo (or a render of a 3D scan) of a used item being listed for resale. `baseline` "
    "shows the product new, from a different angle; use it to know what the intact product looks like. Judge the "
    "physical condition of the item. Ignore photo and scan artifacts: blur, noise, compression blocks, soft or "
    "fuzzy edges, faint speckle or floaters, smeared texture, glare, lighting, exposure, shadows and reflections. "
    "In a scan render, a region never covered looks ragged or hollow; treat that as an artifact unless a solid "
    "part is clearly broken. These ARE condition issues even when they look blurry: scratches or scuffs, "
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
                "even if the photo is a little soft, dark or noisy."
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
                "Most of the visible object is shown clearly enough that a scratch, stain, crack or missing "
                "piece would be noticeable, even if the photo is a little soft or noisy."
            ),
            false=(
                "The object is mostly blur, noise, glare or darkness (or ragged scan), or too small or cut off, "
                "so its condition can't be judged from this image."
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
                "No scratches or scuffs. Blur, noise, glare, reflections, smeared texture and lighting changes "
                "are photo, scan or lighting artifacts, not scratches."
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
                "No cracks or tears. Seams and edges of the design, shadows, and ragged areas a scan didn't "
                "cover are not tears."
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
                "snapped off or clearly broken, and the area around it is clearly visible."
            ),
            false=(
                "Every part that can be seen from this angle is present and intact. Parts hidden by the angle "
                "and areas a photo doesn't show clearly do not count as missing."
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

# Condition without a baseline (no reference photo found): same artifact guidance, judged against what an
# intact product of this kind normally looks like. No question refers to `baseline`.
_WITH_BASELINE_SENTENCE = (
    "`baseline` shows the product new, from a different angle; use it to know what the intact product looks like."
)
_NO_BASELINE_SENTENCE = (
    "No reference photo is available; judge against what an intact product of this kind normally looks like."
)
if _WITH_BASELINE_SENTENCE not in CONDITION_CONTEXT:
    raise RuntimeError("CONDITION_CONTEXT changed: update CONDITION_CONTEXT_NO_BASELINE")
CONDITION_CONTEXT_NO_BASELINE = CONDITION_CONTEXT.replace(_WITH_BASELINE_SENTENCE, _NO_BASELINE_SENTENCE)


def design_features(identity: Identity | None) -> list[str]:
    """What identify read off the item that belongs to its design: printed text and logos, and its colours."""
    if identity is None:
        return []
    features = []
    if identity.visible_text:
        features.append(f"printed text or logos reading {', '.join(repr(t) for t in identity.visible_text)}")
    colours = [f"{k.replace('_', ' ')} {v}" for k, v in identity.attributes.items() if "colour" in k or "color" in k]
    if colours:
        features.append(f"these colours: {'; '.join(colours)}")
    return features


def design_note(identity: Identity | None) -> str:
    """A sentence telling the condition questions that the item's own printing and colours are not damage. Empty
    when identify found neither."""
    features = design_features(identity)
    if not features:
        return ""
    return (
        f" The product's own design includes {' and '.join(features)}. These are part of the design, not damage: "
        "lettering and logos are not scratches, scuffs or stains, even where the photo makes them look streaky, "
        "worn or blurry, and a part in one of these colours is not discolouration."
    )


def condition_context(has_baseline: bool, identity: Identity | None = None) -> str:
    return (CONDITION_CONTEXT if has_baseline else CONDITION_CONTEXT_NO_BASELINE) + design_note(identity)

CONDITION_QUESTIONS_NO_BASELINE = {
    **CONDITION_QUESTIONS,
    "stains_discolouration": Noul(
        instructions=(
            "Following `context`: does the item in `item` have any stains or discolouration that isn't part "
            "of the product's design?"
        ),
        criteria=NoulCriteria(
            true=(
                "A spot, patch or area has a colour that doesn't look like part of the design and isn't a "
                "printed pattern, logo, lighting or reflection: a stain, yellowing, fading or a dirt mark."
            ),
            false=(
                "The colours look like the product's intended design apart from lighting, exposure and "
                "reflections."
            ),
        ),
    ),
    "missing_broken": Noul(
        instructions="Following `context`: is any piece of the item in `item` broken or missing?",
        criteria=NoulCriteria(
            true=(
                "A part an intact product of this kind would have, such as a button, cap, cushion, cover, strap "
                "or tip, is absent, snapped off or clearly broken, and the area around it is clearly visible."
            ),
            false=(
                "Every part that can be seen from this angle is present and intact. Parts hidden by the angle "
                "and areas a photo doesn't show clearly do not count as missing."
            ),
        ),
    ),
}

BASELINE_CONTEXT = (
    "`photo` is an image search result being considered as a clean reference photo of the product described "
    "in `query`. A good reference shows that one product on its own, like a manufacturer or shop product shot."
)

BASELINE_QUESTIONS = {
    "single_product": Noul(
        instructions="Following `context`: does `photo` show exactly one product as its subject?",
        criteria=NoulCriteria(
            true=(
                "One product is the clear subject. A set sold and shown together, such as a pair of earbuds, "
                "or headphones with their cable, counts as one product."
            ),
            false="Several products, several copies of the product, or no clear single product are shown.",
        ),
    ),
    "plain_background": Noul(
        instructions="Following `context`: is the background of `photo` plain?",
        criteria=NoulCriteria(
            true="A flat or softly graded single colour, such as white or light grey, with nothing else in it.",
            false="A room, table, outdoor scene, pattern, furniture, or other objects behind or around the product.",
        ),
    ),
    "people_or_packaging": Noul(
        instructions="Following `context`: does `photo` show any person or any packaging?",
        criteria=NoulCriteria(
            true="Any person, face, hand or other body part, or any box, bag, blister pack or retail packaging.",
            false="Only the product itself, with no people, hands or packaging anywhere in the image.",
        ),
    ),
    "overlay_or_collage": Noul(
        instructions="Following `context`: is `photo` a collage or covered by added graphics?",
        criteria=NoulCriteria(
            true=(
                "A collage or grid of several pictures, or large added text, badges, prices, arrows or "
                "watermarks over the image."
            ),
            false="A single photo with no added text or graphics, apart from what is printed on the product.",
        ),
    ),
    "matches_query": Noul(
        instructions="Following `context`: is the product in `photo` the product described by `query`?",
        criteria=NoulCriteria(
            true=(
                "Same kind of product, and the same brand and model wherever `query` names them. A different "
                "colour counts as a match only if `query` doesn't name a colour."
            ),
            false="A different kind of product, a different brand or model, an accessory, or a part of the product.",
        ),
    ),
}

TASKS: dict[str, tuple[str, dict[str, Any]]] = {
    "gate": (GATE_CONTEXT, GATE_QUESTIONS),
    "condition": (CONDITION_CONTEXT, CONDITION_QUESTIONS),
}


def build_state(context: str, baseline: Image, item: Image) -> dict[str, Any]:
    return {"context": context, "baseline": baseline, "item": item}
