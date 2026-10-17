import pytest

from buyer_agent.config import JEV_MODEL_PIN, load_settings
from buyer_agent.jev_client import LiveJev
from buyer_agent.jev_prompts import claim_question

pytestmark = pytest.mark.live


async def test_one_live_text_only_call():
    live = LiveJev(load_settings())
    r = await live.ask(
        {"view_1": "a red mug on a table", "claim_text": "red mug"}, {"c": claim_question()}
    )
    assert r.model == JEV_MODEL_PIN and 0.0 <= r.nouls["c"] <= 1.0
    await live.aclose()
