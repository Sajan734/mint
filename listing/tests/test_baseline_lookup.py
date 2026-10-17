import pytest

from contracts import Identity
from stages.baseline_lookup import baseline_query

IDENTITY = Identity(
    category="in-ear headphones", brand="Sony", model=None, visible_text=["SONY"],
    search_query="Sony black in-ear headphones", confidence=0.9,
)


@pytest.mark.parametrize(
    "seller_name, expected",
    [
        ("Sony WI-XB400", "Sony WI-XB400"),  # the seller's product name wins over the identified query
        ("  Sony WI-XB400  ", "Sony WI-XB400"),
        (None, "Sony black in-ear headphones"),
        ("   ", "Sony black in-ear headphones"),
    ],
)
def test_seller_name_takes_priority(seller_name, expected):
    assert baseline_query(IDENTITY, seller_name) == expected
