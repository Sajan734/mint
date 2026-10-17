import json

import pytest

from buyer_agent.config import load_settings
from buyer_agent.groq_client import LiveGroq

pytestmark = pytest.mark.live


async def test_one_live_json_draft():
    s = load_settings()
    r = await LiveGroq(s).chat(
        s.groq_model_fast, "Reply with JSON only.", 'Return {"ok": true} as JSON.'
    )
    assert isinstance(json.loads(r.text), dict)
