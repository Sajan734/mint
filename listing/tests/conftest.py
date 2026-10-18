"""Shared test guards. Tests never call a real API: the repo .env has real keys, so by default every client that would
reach Serper, Gemini or Jev fails like an offline network. Tests that exercise a stage replace these with fakes."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def no_serper_shopping(monkeypatch):
    """reference_price's first source is a real Serper search."""
    import stages.reference_price as rp

    async def offline(query, api_key):
        raise httpx.ConnectError("tests never call Serper")

    monkeypatch.setattr(rp, "search_shopping", offline)


class _OfflineClient:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("tests never call a real API")


@pytest.fixture(autouse=True)
def no_gemini_or_jev(monkeypatch):
    """The pipeline starts stages speculatively (listing_text, reference_price and condition run beside the match
    check), so a fixture that is rejected would otherwise reach Gemini and Jev before it's cancelled."""
    import google.genai

    import stages.baseline_lookup as bl
    import stages.condition as cond
    import stages.match_gate as mg

    monkeypatch.setattr(google.genai, "Client", _OfflineClient)
    for module in (bl, cond, mg):
        monkeypatch.setattr(module, "AsyncTypeSafeClient", _OfflineClient)


@pytest.fixture(autouse=True)
def no_lens_or_sources(monkeypatch):
    """identify's Lens search (with its photo upload) and listing_text's model sources search go straight to httpx.
    Tests of those functions call the originals, imported before this patch."""
    import stages.lens as lens
    import stages.listing_text as lt

    async def no_lens(views, item_id):
        return [], {"error": "tests never call Lens"}

    async def no_sources(identity):
        return [], {"skipped": "tests never search for sources"}

    monkeypatch.setattr(lens, "lens_matches", no_lens)
    monkeypatch.setattr(lt, "fetch_sources", no_sources)
