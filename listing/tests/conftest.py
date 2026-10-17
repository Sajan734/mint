"""Shared test guards. Tests never call a real API."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def no_serper_shopping(monkeypatch):
    """reference_price's first source is a real Serper search, and the repo .env has the key, so by default the
    search fails like an offline network. Tests of the listings source replace search_shopping themselves."""
    import stages.reference_price as rp

    async def offline(query, api_key):
        raise httpx.ConnectError("tests never call Serper")

    monkeypatch.setattr(rp, "search_shopping", offline)
