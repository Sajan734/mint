"""Every Gemini call in listing/ uses the one model set in GEMINI["model"], whatever GEMINI_MODEL says. No API calls:
google.genai's client is faked and records the model it was asked for."""

import asyncio
from types import SimpleNamespace

import pytest

import stages.identify as identify
from gemini import generate_json
from stages.identify import GEMINI, gemini_model


@pytest.fixture
def requested(monkeypatch):
    import google.genai as genai

    models = []

    class FakeModels:
        async def generate_content(self, model, contents, config):
            models.append(model)
            return SimpleNamespace(text='{"ok": true}', model_version=None, usage_metadata=None, candidates=[])

    class FakeClient:
        def __init__(self, api_key):
            self.aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")  # what the team's .env still says
    return models


def test_the_one_setting_is_flash_lite():
    assert GEMINI["model"] == "gemini-3.5-flash-lite"


def test_environment_override_is_ignored_with_a_warning(monkeypatch, capsys):
    identify._warn_ignored_model.cache_clear()
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    assert gemini_model() == gemini_model() == "gemini-3.5-flash-lite"
    err = capsys.readouterr().err
    assert err.count("ignoring GEMINI_MODEL=gemini-3.8-flash") == 1  # warned once, not on every call


def test_listing_text_reference_price_and_highlight_use_it(requested):
    """They all call gemini.generate_json."""
    asyncio.run(generate_json("hi", "system", {"type": "object"}))
    assert requested == ["gemini-3.5-flash-lite"]


@pytest.mark.parametrize("grounding, calls", [(False, [False]), (True, [True, False])])
def test_grounded_price_lookup_only_when_search_grounding_is_on(monkeypatch, grounding, calls):
    """Our free-tier project can't use Search grounding (0/day on Gemini 3+, 2.5 models closed to new projects),
    so with it off the price stage makes one ungrounded call instead of a doomed grounded one first."""
    import stages.reference_price as rp
    from contracts import Identity

    asked = []

    async def fake(contents, system_prompt, schema, *, tools=None, **kwargs):
        asked.append(bool(tools))
        raise RuntimeError("429")  # every source fails, so the category default is used

    monkeypatch.setattr(rp, "generate_json", fake)
    monkeypatch.setitem(GEMINI, "search_grounding", grounding)
    identity = Identity(category="wireless mouse", visible_text=["ThinkPad"], search_query="mouse", confidence=0.9)
    price, _log = asyncio.run(rp.look_up(identity, None))
    assert asked == calls and price.basis == "llm_estimate"


def test_search_grounding_is_off_on_the_free_tier():
    assert GEMINI["search_grounding"] is False


def test_identify_uses_it(requested, monkeypatch):
    from contracts import Views

    monkeypatch.setattr(identify, "build_contents", lambda views: ([], []))
    result = asyncio.run(identify.call_gemini(Views.model_construct(item_id="t", views=[])))
    assert requested == ["gemini-3.5-flash-lite"] and result.model == "gemini-3.5-flash-lite"
