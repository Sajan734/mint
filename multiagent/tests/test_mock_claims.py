import json
from pathlib import Path

import pytest

from buyer_agent.models import ListingClaims

CLAIMS = Path(__file__).resolve().parent.parent / "mock" / "claims"
NAMES = ["pots_truthful", "pots_exaggerated", "pots_missing_accessory"]


@pytest.mark.parametrize("name", NAMES)
def test_mock_claims_validate_as_listing_claims(name):
    claims = ListingClaims.model_validate(json.loads((CLAIMS / f"{name}.json").read_text()))
    assert claims.title and claims.accessories_included
