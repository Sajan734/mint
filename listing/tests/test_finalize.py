import pytest

from contracts import Baseline, Condition, Defect, ListingDraft, MatchCheck, ReferencePrice, View, Views
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
BASELINE = Baseline(query="headphones", image_path="baseline.jpg", source="manual")


@pytest.mark.parametrize(
    "amount, basis, grade, expected",
    [
        (230.0, "used_comps", "light_wear", 150),  # 149.5 rounds half up to the nearest $5
        (230.0, "used_comps", "like_new", 185),  # 184 -> 185
        (449.99, "new_retail", "like_new", 360),  # 359.992 -> 360
        (100.0, "new_retail", "moderate_wear", 50),
        (100.0, "llm_estimate", "heavy_wear", 30),
        (4.0, "used_comps", "heavy_wear", PRICE["floor_cad"]),  # 1.20 is raised to the floor
    ],
)
def test_compute_price(amount, basis, grade, expected):
    price, sentence = compute_price(ReferencePrice(amount_cad=amount, basis=basis, note="n"), make_condition(grade))
    assert price == expected
    assert f"${expected}" in sentence


def test_compute_price_is_deterministic():
    ref = ReferencePrice(amount_cad=187.35, basis="new_retail", note="n")
    assert compute_price(ref, make_condition()) == compute_price(ref, make_condition())


def test_notes_skip_low_scores_and_sort_by_score():
    defects = [
        Defect(kind="wear", score=0.64, view_ids=["v04", "v05", "v06"]),
        Defect(kind="scuff", score=0.71, view_ids=["v02"]),
        Defect(kind="dent", score=0.40, view_ids=["v01"]),
    ]
    assert build_notes(defects, make_views()) == [
        "The view 2 view shows a scuff.",
        "3 views show signs of wear: view 4; view 5; view 6.",
    ]


def test_notes_when_nothing_notable():
    assert build_notes([Defect(kind="dent", score=0.2, view_ids=["v01"])], make_views()) == [NO_DEFECTS_NOTE]


def test_match_listing_needs_no_check():
    listing = build_listing(make_views(), make_match("match"), BASELINE, DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"), make_condition())
    assert listing.needs_seller_check is False
    assert listing.seller_check_reasons == []


def test_uncertain_match_flags_seller_check():
    match = make_match("uncertain")
    listing = build_listing(make_views(), match, BASELINE, DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"), make_condition())
    assert listing.needs_seller_check is True
    assert listing.seller_check_reasons == [match.reason]


def test_condition_flag_carries_through():
    listing = build_listing(
        make_views(), make_match(), BASELINE, DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"),
        make_condition(needs_seller_check=True),
    )
    assert listing.needs_seller_check is True
    assert listing.seller_check_reasons == [CONDITION_CHECK_REASON]


def test_previews_use_low_ring_views():
    listing = build_listing(make_views(), make_match(), BASELINE, DRAFT, ReferencePrice(amount_cad=100, basis="used_comps", note="n"), make_condition())
    assert listing.preview_images == ["v00.png", "v02.png", "v04.png", "v06.png"]
