"""stages/lens.py: picking photos, reading Serper's Lens answer, counting support, and failing softly (no network:
the matches are a real recorded Serper response, and the HTTP calls are faked)."""

import asyncio
import json
from pathlib import Path

import httpx

import stages.lens as lens
from contracts import View, Views

PAYLOAD = json.loads((Path(__file__).parent / "data" / "serper_lens_thinkpad.json").read_text(encoding="utf-8"))
REAL_LENS_MATCHES = lens.lens_matches  # conftest replaces lens_matches; these tests exercise the real one


def views(n, url=None):
    return Views(item_id="item", views=[View(view_id=f"p{i:02d}", label=f"photo {i}", image_path=f"p{i:02d}.jpg",
                                             source_url=url) for i in range(1, n + 1)])


def test_the_first_photo_and_one_from_the_other_side_are_searched():
    assert [v.view_id for v in lens.picked_views(views(8))] == ["p01", "p05"]
    assert [v.view_id for v in lens.picked_views(views(1))] == ["p01"]  # one photo is searched once


def test_real_answer_parses_into_titled_matches():
    matches = lens.parse_matches(PAYLOAD, "p01")
    assert len(matches) == 30 and matches[1].title.startswith("Lenovo Wireless Multi-Mode Pro Mouse 6000")
    assert lens.support("Lenovo", matches) == (9, 5) and lens.support(None, matches) == (0, 0)


def test_prompt_titles_alternate_between_photos_without_repeats():
    a = [lens.LensMatch(t, None, None, "p01") for t in ("A", "B", "C")]
    b = [lens.LensMatch(t, None, None, "p05") for t in ("x", "a", "Y")]
    assert lens.titles_for_prompt(a + b, 10) == ["A", "x", "B", "C", "Y"]  # "a" repeats "A"


class FakeClient:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(url)
        status, body = self.routes(url, kwargs)
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


def run_lens(monkeypatch, routes, the_views, env):
    client = FakeClient(routes)
    monkeypatch.setattr(lens.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(lens, "_env", lambda name: env.get(name, ""))
    return asyncio.run(REAL_LENS_MATCHES(the_views, "item")), client


def test_public_urls_go_straight_to_lens(monkeypatch):
    (matches, log), client = run_lens(monkeypatch, lambda url, kw: (200, PAYLOAD),
                                      views(8, url="https://x.test/p.jpg"), {"SERPER_API_KEY": "k"})
    assert len(matches) == 60 and client.calls == [lens.LENS["endpoint"]] * 2  # two photos, no uploads


def test_without_a_url_the_photo_is_uploaded_first(monkeypatch, tmp_path):
    photo = tmp_path / "p01.jpg"
    photo.write_bytes(b"jpeg")
    monkeypatch.setattr(lens, "LISTING_ROOT", tmp_path)
    one = Views(item_id="item", views=[View(view_id="p01", label="photo 1", image_path="p01.jpg")])
    env = {"SERPER_API_KEY": "k", "SUPABASE_URL": "https://sb.test", "SUPABASE_SERVICE_ROLE_KEY": "s"}
    (matches, log), client = run_lens(monkeypatch, lambda url, kw: (200, PAYLOAD if "serper" in url else {}), one, env)
    assert client.calls[0] == "https://sb.test/storage/v1/object/assets/listing-photos/item/p01.jpg"
    assert log["photos"][0]["url"] == "https://sb.test/storage/v1/object/public/assets/listing-photos/item/p01.jpg"
    assert len(matches) == 30


def test_no_supabase_key_means_no_lens_but_no_failure(monkeypatch):
    (matches, log), client = run_lens(monkeypatch, lambda url, kw: (200, PAYLOAD), views(2), {"SERPER_API_KEY": "k"})
    assert matches == [] and client.calls == []
    assert all("SUPABASE_SERVICE_ROLE_KEY" in p["error"] for p in log["photos"])


def test_a_failing_search_is_logged_not_raised(monkeypatch):
    (matches, log), _ = run_lens(monkeypatch, lambda url, kw: (500, {}), views(8, url="https://x.test/p.jpg"),
                                 {"SERPER_API_KEY": "k"})
    assert matches == [] and "HTTPStatusError" in log["photos"][0]["error"]


def test_no_serper_key(monkeypatch):
    (matches, log), client = run_lens(monkeypatch, lambda url, kw: (200, PAYLOAD), views(8), {})
    assert matches == [] and log["error"] == "SERPER_API_KEY is missing" and client.calls == []
