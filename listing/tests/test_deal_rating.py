import pytest

from contracts import Baseline, Condition, Defect, MatchCheck, ReferencePrice
from stages.deal_rating import DEAL, asking_price, band, rate, rate_deal, uncertainty
from stages.reference_price import default_price

NEW = ReferencePrice(amount_cad=200.0, basis="new_retail", note="Search-grounded new price: sony.ca.")
MATCH = MatchCheck(same_category=0.9, same_product=0.9, verdict="match", reason="match")
BASELINE = Baseline(query="headphones", image_path="baseline.jpg", source="manual")


def make_condition(grade="light_wear", defects=(), needs_seller_check=False):
    return Condition(grade=grade, grade_score=0.8, grade_confidence=0.8, defects=list(defects),
                     usable_view_count=12, needs_seller_check=needs_seller_check)


@pytest.mark.parametrize(
    "ratio, label",
    [(0.5, "great"), (0.85, "great"), (0.86, "good"), (0.95, "good"), (1.0, "fair"), (1.10, "fair"),
     (1.2, "high"), (1.30, "high"), (1.31, "overpriced")],
)
def test_bands_match_the_buyer_badge_plus_good(ratio, label):
    assert band(ratio) == label


# The three cases from the brief. Fair prices: like new 0.80, moderate wear 0.50, heavy wear 0.30 of new.
@pytest.mark.parametrize(
    "grade, asking, label",
    [
        ("like_new", 130, "great"),  # negligible damage, 35% below new: 130 / 160 = 0.81
        ("like_new", 140, "good"),  # 30% below new: 140 / 160 = 0.875
        ("moderate_wear", 100, "fair"),  # badly scuffed at half price: the discount is what the wear costs
        ("heavy_wear", 100, "overpriced"),  # half price but worth 60: 100 / 60 = 1.67
        ("light_wear", 130, "fair"),  # 130 / 130
    ],
)
def test_condition_not_discount_decides(grade, asking, label):
    deal = rate_deal(NEW, make_condition(grade), MATCH, BASELINE, asking)
    assert deal.rating == label
    assert deal.confidence == "high" and deal.confidence_notes == []


def test_same_discount_rates_differently_by_condition():
    """A 50% discount is great for a like-new item and overpriced for a heavily worn one."""
    ratings = [rate_deal(NEW, make_condition(g), MATCH, BASELINE, 100).rating
               for g in ("like_new", "moderate_wear", "heavy_wear")]
    assert ratings == ["great", "fair", "overpriced"]


def test_priced_defects_lower_the_fair_price():
    cracked = make_condition("light_wear", [Defect(kind="crack", score=0.9, view_ids=["v01"])])
    deal = rate_deal(NEW, cracked, MATCH, BASELINE, 130)
    assert deal.fair_price_cad == 110  # 200 x 0.65 x 0.85 = 110.50, to the nearest $5
    assert deal.rating == "high"
    assert "With light wear and a crack or tear we'd expect about $110" in deal.explanation


def test_no_asking_price_rates_the_suggested_price():
    deal = rate_deal(NEW, make_condition(), MATCH, BASELINE, None)
    assert deal.asking_price_source == "suggested"
    assert deal.asking_price_cad == deal.fair_price_cad == 130
    assert deal.rating == "fair" and deal.ratio_to_fair == 1.0
    assert "No asking price was given" in deal.explanation


def test_explanation_carries_the_real_numbers():
    deal = rate_deal(NEW, make_condition("like_new"), MATCH, BASELINE, 120)
    assert deal.explanation == (
        "Great deal. Asking $120 is 40% below the new price of about $200. In like-new condition we'd expect about "
        "$160 (20% below new), so the asking price is 25% below what it's worth in this condition."
    )


def test_fair_explanation_says_the_discount_is_what_the_condition_costs():
    deal = rate_deal(NEW, make_condition("moderate_wear"), MATCH, BASELINE, 100)
    assert "the 50% discount is about what its condition costs" in deal.explanation


@pytest.mark.parametrize(
    "reference, match_verdict, baseline_path, check, expected_u, notes",
    [
        (NEW, "match", "b.jpg", False, 0.0, 0),
        (ReferencePrice(amount_cad=200, basis="llm_estimate", note="Model estimate, not looked up: x."),
         "match", "b.jpg", False, 0.20, 1),
        (default_price("over-ear headphones"), "match", "b.jpg", False, 0.35, 1),  # replaces llm_estimate
        (NEW, "uncertain", "b.jpg", False, 0.15, 1),
        (NEW, "match", None, False, 0.10, 1),
        (NEW, "match", "b.jpg", True, 0.10, 1),
        (default_price("headphones"), "uncertain", None, True, DEAL["max_uncertainty"], 4),  # capped
    ],
)
def test_weak_inputs_widen_the_fair_price(reference, match_verdict, baseline_path, check, expected_u, notes):
    match = MatchCheck(same_category=0.9, same_product=0.5, verdict=match_verdict, reason="r")
    baseline = Baseline(query="q", image_path=baseline_path, source="manual")
    u, weak = uncertainty(reference, make_condition(needs_seller_check=check), match, baseline)
    assert u == pytest.approx(expected_u)
    assert len(weak) == notes


@pytest.mark.parametrize("u, confidence", [(0.0, "high"), (0.10, "medium"), (0.25, "medium"), (0.35, "low")])
def test_confidence_from_uncertainty(u, confidence):
    from stages.deal_rating import confidence_for

    assert confidence_for(u) == confidence


def test_shaky_numbers_dont_claim_a_great_deal():
    """Same asking price as a great deal, but the new price is a model estimate and the match is unconfirmed."""
    guessed = ReferencePrice(amount_cad=200, basis="llm_estimate", note="Model estimate, not looked up: x.")
    uncertain = MatchCheck(same_category=0.9, same_product=0.5, verdict="uncertain", reason="r")
    deal = rate_deal(guessed, make_condition("like_new"), uncertain, BASELINE, 120)
    assert deal.rating == "fair"
    assert deal.confidence == "low"
    assert "On these numbers alone it would be a great deal" in deal.explanation
    assert "the new price is a model estimate" in deal.explanation


def test_shaky_numbers_dont_claim_overpriced_either():
    guessed = ReferencePrice(amount_cad=200, basis="llm_estimate", note="Model estimate, not looked up: x.")
    uncertain = MatchCheck(same_category=0.9, same_product=0.5, verdict="uncertain", reason="r")
    deal = rate_deal(guessed, make_condition("light_wear"), uncertain, BASELINE, 160)  # 160 / 130 = 1.23
    assert deal.rating == "fair"
    assert "On these numbers alone it would be a bit high" in deal.explanation


def test_clear_cut_cases_survive_low_confidence():
    guessed = ReferencePrice(amount_cad=200, basis="llm_estimate", note="Model estimate, not looked up: x.")
    assert rate_deal(guessed, make_condition("heavy_wear"), MATCH, BASELINE, 150).rating == "overpriced"  # 2.5x
    assert rate_deal(guessed, make_condition("like_new"), MATCH, BASELINE, 60).rating == "great"


@pytest.mark.parametrize("asking, fair, u, expected", [(100, 100, 0.0, ("fair", "fair")),
                                                        (80, 100, 0.2, ("fair", "great")),
                                                        (60, 100, 0.2, ("great", "great")),
                                                        (140, 100, 0.2, ("high", "overpriced")),
                                                        (120, 100, 0.2, ("fair", "high")),
                                                        (160, 100, 0.2, ("overpriced", "overpriced"))])
def test_rate_holds_across_the_range(asking, fair, u, expected):
    assert rate(asking, fair, u) == expected


def test_rating_is_deterministic():
    args = (NEW, make_condition("moderate_wear"), MATCH, BASELINE, 87.5)
    assert rate_deal(*args) == rate_deal(*args)


@pytest.mark.parametrize("value", [0, -1, "120", True, float("inf")])
def test_asking_price_must_be_a_positive_number(value):
    with pytest.raises(ValueError, match="asking_price_cad"):
        asking_price(value)


def test_asking_price_accepts_ints_and_none():
    assert asking_price(120) == 120.0 and asking_price(None) is None
