import pytest

from contracts import Condition, Defect, ListingDraft, MatchCheck, ReferencePrice, View, Views
from stages.finalize import (
    CONDITION_CHECK_REASON,
    NO_DEFECTS_NOTE,
    PRICE,
    build_listing,
    build_notes,
    compute_price,
)


def make_views(n=12):
    return Views(
        item_id="test",
        views=[
            View(view_id=f"v{i:02d}", label=f"view {i}", azimuth_deg=0, elevation_deg=10, image_path=f"v{i:02d}.png")
            for i in range(n)
        ],
    )


def make_match(verdict="match"):
    return MatchCheck(same_category=0.9, same_product=0.9, verdict=verdict, reason=f"{verdict} reason")


def make_condition(grade="light_wear", needs_seller_check=False, defects=()):
    return Condition(
        grade=grade,
        grade_score=0.8,
        grade_confidence=0.8,
        defects=list(defects),
        usable_view_count=12,
        needs_seller_check=needs_seller_check,
    )


DRAFT = ListingDraft(title="Headphones", description="Over-ear headphones.", attributes={}, tags=[])


@pytest.mark.parametrize(
    "amount, basis, grade, expected",
    [
        (230.0, "used_comps", "light_wear", 207),
        (230.0, "used_comps", "like_new", 230),
        (449.99, "new_retail", "like_new", 315),  # 314.993 -> 315
        (100.0, "new_retail", "moderate_wear", 53),  # 52.5 rounds half up
        (100.0, "llm_estimate", "heavy_wear", 39),  # 38.5 rounds half up
        (4.0, "used_comps", "heavy_wear", PRICE["min_price_cad"]),  # clamped to the minimum
    ],
)
def test_compute_price(amount, basis, grade, expected):
    price, lines = compute_price(ReferencePrice(amount_cad=amount, basis=basis, note="n"), grade)
    assert price == expected
    assert lines[-1] == f"Asking price: ${expected:,} CAD"


def test_compute_price_is_deterministic():
    ref = ReferencePrice(amount_cad=187.35, basis="new_retail", note="n")
    assert compute_price(ref, "light_wear") == compute_price(ref, "light_wear")


def test_notes_skip_low_scores_and_sort_by_score():
    defects = [
        Defect(kind="wear", score=0.64, view_ids=["v04", "v05", "v06"]),
        Defect(kind="scuff", score=0.71, view_ids=["v02"]),
        Defect(kind="dent", score=0.40, view_ids=["v01"]),
    ]
    assert build_notes(defects) == ["Scuff (seen in 1 view)", "Signs of wear (seen in 3 views)"]


def test_notes_when_nothing_notable():
    assert build_notes([Defect(kind="dent", score=0.2, view_ids=["v01"])]) == [NO_DEFECTS_NOTE]


def test_match_listing_needs_no_check():
    listing = build_listing(make_views(), make_match("match"), DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"), make_condition())
    assert listing.needs_seller_check is False
    assert listing.seller_check_reasons == []


def test_uncertain_match_flags_seller_check():
    match = make_match("uncertain")
    listing = build_listing(make_views(), match, DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"), make_condition())
    assert listing.needs_seller_check is True
    assert listing.seller_check_reasons == [match.reason]


def test_condition_flag_carries_through():
    listing = build_listing(
        make_views(), make_match(), DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"),
        make_condition(needs_seller_check=True),
    )
    assert listing.needs_seller_check is True
    assert listing.seller_check_reasons == [CONDITION_CHECK_REASON]


def test_previews_use_low_ring_views():
    listing = build_listing(make_views(), make_match(), DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"), make_condition())
    assert listing.preview_images == ["v00.png", "v02.png", "v04.png", "v06.png"]
