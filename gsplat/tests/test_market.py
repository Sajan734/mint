"""market.carry_over: running the listing step again keeps the seller's work. python -m pytest gsplat/tests"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mintsplat.market import carry_over  # noqa: E402


def listed(title, price, published=False, **extra):
    ml = {"listing": {"title": title, "description": f"{title} desc", "price_cad": price}, "listed_at": "T1"}
    return {"status": "listed", "market_listing": ml, "published": published, **extra}


def test_first_run_is_unchanged():
    doc = listed("New", 40)
    assert carry_over(None, doc) is doc


def test_failed_rerun_keeps_the_listing():
    prev = listed("Mouse", 25, published=True)
    out = carry_over(prev, {"status": "failed", "error": "Gemini 503"})
    assert out["status"] == "listed" and out["published"] is True
    assert out["market_listing"]["listing"]["title"] == "Mouse"
    assert out["relist_error"] == "Gemini 503"


def test_published_listing_stays_published_with_the_sellers_edits():
    prev = listed("Seller title", 30, published=True, published_at="P")
    out = carry_over(prev, listed("Pipeline title", 45))
    listing = out["market_listing"]["listing"]
    assert out["published"] is True and out["published_at"] == "P"
    assert (listing["title"], listing["price_cad"]) == ("Seller title", 30)
    assert out["suggested_price_cad"] == 45
    assert out["market_listing"]["listed_at"] == "T1"


def test_unpublished_draft_takes_the_new_run():
    out = carry_over(listed("Old", 20), listed("New", 40))
    assert out["market_listing"]["listing"]["title"] == "New" and out["published"] is False


def test_rejected_rerun_replaces_an_earlier_failure():
    doc = {"status": "rejected"}
    assert carry_over({"status": "failed"}, doc) is doc
