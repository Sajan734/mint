"""Adapter: teammate's `listing` pipeline output (their `Listing` JSON) -> our ListingClaims.

Their package is NOT imported. `_Listing` mirrors the fields of listing/contracts.py `Listing`
(origin/listing) that we use; anything else is ignored.
"""

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from buyer_agent.models import ListingClaims, Price

# Their 4-level wear grade -> our 1-10 scale (half steps). Chosen so that only `like_new`
# reaches >= 9, which claims.py treats as an unverifiable "perfect" claim; `light_wear` matches
# the 8 used in mock/claims. Tune with the eval set, not by hand.
GRADE_TO_SCORE: dict[str, float] = {
    "like_new": 9.0,
    "light_wear": 7.5,
    "moderate_wear": 5.0,
    "heavy_wear": 2.5,
}
CORE_ATTRS = {"brand", "model", "type", "category"}
ACCESSORY_KEYS = ("accessories", "includes", "included", "accessories_included")
# Only explicit statements count; a bare "with" ("headphones with noise cancelling") does not.
_STATED_RE = re.compile(
    r"\b(?:comes with|come with|includes?|included|together with)\s+([^.;\n]+)", re.IGNORECASE
)
_SPLIT_RE = re.compile(r",|;|\band\b|\+", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"^(?:a|an|the|one|some)\s+", re.IGNORECASE)
# finalize.py's filler note; it says nothing checkable, so it is never sent as a claim.
_FILLER_NOTES = ("no defects stood out",)
LISTING_KEYS = {"price_cad", "attributes", "preview_images", "item_id", "description", "tags"}


class _Listing(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(min_length=1)
    description: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    condition_grade: Literal["like_new", "light_wear", "moderate_wear", "heavy_wear"] | None = None
    condition_notes: list[str] = Field(default_factory=list)
    price_cad: float | None = Field(default=None, gt=0)


def is_listing_format(data: dict[str, Any]) -> bool:
    """Native claims have `accessories_included`/`price`/`specs`; their Listing has these keys."""
    return bool(LISTING_KEYS & data.keys()) or isinstance(data.get("condition_grade"), str)


def _clean(items: list[str]) -> list[str]:
    out: list[str] = []
    for raw in items:
        item = _ARTICLE_RE.sub("", raw.strip().strip(".")).strip()
        if item and item.lower() not in {o.lower() for o in out}:
            out.append(item[:100])
    return out


def stated_accessories(listing: _Listing) -> list[str]:
    """Accessories the seller explicitly states: attribute keys or 'includes X' sentences."""
    found: list[str] = []
    for key in ACCESSORY_KEYS:
        if listing.attributes.get(key):
            found += _SPLIT_RE.split(listing.attributes[key])
    for match in _STATED_RE.finditer(listing.description):
        found += _SPLIT_RE.split(match.group(1))
    return _clean(found)[:10]


def claims_from_listing(listing: dict[str, Any] | str | _Listing) -> ListingClaims:
    """Map their Listing contract to ListingClaims. Raises pydantic ValidationError if invalid."""
    if isinstance(listing, str):
        listing = json.loads(listing)
    item = listing if isinstance(listing, _Listing) else _Listing.model_validate(listing)
    attrs = item.attributes
    notes = [
        n[:200] for n in item.condition_notes if not any(f in n.lower() for f in _FILLER_NOTES)
    ]
    return ListingClaims(
        title=item.title[:200],
        brand=attrs.get("brand"),
        model=attrs.get("model"),
        category=attrs.get("type") or attrs.get("category"),
        specs={k: v for k, v in attrs.items() if k not in CORE_ATTRS | set(ACCESSORY_KEYS)},
        condition_grade=GRADE_TO_SCORE.get(item.condition_grade) if item.condition_grade else None,
        condition_notes=notes[:10],
        accessories_included=stated_accessories(item),
        price=Price(amount=item.price_cad, currency="CAD") if item.price_cad else None,
    )


def parse_claims(data: dict[str, Any]) -> ListingClaims:
    """Native claims format or their Listing format, detected by keys."""
    if is_listing_format(data):
        return claims_from_listing(data)
    return ListingClaims.model_validate(data)


def load_listing_claims(path: Path | str) -> ListingClaims:
    return parse_claims(json.loads(Path(path).read_text(encoding="utf-8")))
