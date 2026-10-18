"""identify stage: the claim rule (decide), the read/Lens/fuse orchestration, request building, offline fixture path.
No Gemini or Serper calls: the Lens matches are a real recorded Serper response."""

import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image as PILImage

import stages.identify as identify_mod
from contracts import RunContext, View, Views
from gemini import GeminiReply
from pipeline import ROOT
from stages.identify import GEMINI, IDENTIFY, GeminiResult, MissingKeyError, decide, read_fields, response_schema
from stages.lens import LensMatch, parse_matches, support

LENS_PAYLOAD = json.loads((Path(__file__).parent / "data" / "serper_lens_thinkpad.json").read_text(encoding="utf-8"))
MOUSE_LENS = parse_matches(LENS_PAYLOAD, "p01")  # 9 titles say Lenovo (5 sites), 2 say ThinkPad, none a model


def read(**overrides):
    base = {"category": "wireless mouse", "visible_text": ["ThinkPad"], "brand": "Lenovo",
            "model": "ThinkPad Bluetooth Silent Mouse", "attributes": {"Colour": "black"},
            "search_query": "Lenovo ThinkPad wireless mouse", "confidence": 0.85}
    return read_fields(base | overrides)


def lens(*titles, sources=None):
    return [LensMatch(title=t, source=(sources or [f"site{i}" for i in range(len(titles))])[i], link=None,
                      view_id="p01") for i, t in enumerate(titles)]


MX = lens("Logitech MX Master 3S Wireless Mouse", "MX Master 3S review", "Logitech MX Master 3S - Graphite",
          "Logitech MX Master 3S Performance Mouse")


# --- the claim rule ------------------------------------------------------------------------------


def test_real_lens_backs_the_brand_but_not_a_model():
    identity, notes = decide(read(), None, None, MOUSE_LENS)
    assert identity.brand == "Lenovo" and identity.model is None and identity.specificity == "brand"
    assert identity.product_name == "Lenovo wireless mouse" == identity.search_query
    assert identity.evidence == ["brand 'Lenovo': lens (9 titles, 5 sources)"]
    assert any("model 'ThinkPad Bluetooth Silent Mouse' not claimed" in n for n in notes)


def test_without_lens_a_printed_product_line_is_the_brand():
    identity, notes = decide(read(), None, None, [])
    assert identity.brand == "ThinkPad" and identity.product_name == "ThinkPad wireless mouse"
    assert "brand 'Lenovo' not claimed: nothing backs it" in notes


@pytest.mark.parametrize(
    "visible, seller, matches, expected_model, expected_specificity",
    [
        (["MX Master 3S", "logi"], None, MX, "MX Master 3S", "model"),  # printed + Lens
        ([], "Logitech MX Master 3S", MX, "MX Master 3S", "model"),  # seller + Lens
        (["MX Master 3S"], "my Logitech MX Master 3S", [], "MX Master 3S", "model"),  # printed + seller
        (["MX Master 3S"], "my MX Master 3S", [], None, "type"),  # a model, but nothing names the brand
        ([], None, MX, None, "brand"),  # Lens alone: brand, not the model
        (["MX Master 3S"], None, [], None, "type"),  # printed model but no brand backed
        ([], None, [], None, "type"),  # nothing backs anything
    ],
)
def test_an_exact_model_needs_two_kinds_of_evidence(visible, seller, matches, expected_model, expected_specificity):
    r = read(visible_text=visible, brand="Logitech", model="MX Master 3S", category="wireless mouse",
             search_query="Logitech MX Master 3S")
    identity, _ = decide(r, None, seller, matches)
    assert identity.model == expected_model and identity.specificity == expected_specificity


def test_lens_needs_several_titles_from_several_sites():
    one_site = lens(*["Logitech MX Master 3S"] * 5, sources=["amazon"] * 5)
    assert support("MX Master 3S", one_site) == (5, 1)
    identity, _ = decide(read(visible_text=[], brand="Logitech", model="MX Master 3S"), None, None, one_site)
    assert identity.specificity == "type"  # one site saying it five times isn't agreement


def test_the_fused_candidate_comes_first_and_is_still_checked():
    candidate = {"brand": "Logitech", "model": "MX Master 3S", "product_type": "wireless ergonomic mouse"}
    identity, _ = decide(read(visible_text=["MX Master 3S"], brand=None, model=None), candidate, None, MX)
    assert identity.product_name == "Logitech MX Master 3S" and identity.category == "wireless ergonomic mouse"
    wrong = {"brand": "Razer", "model": "DeathAdder", "product_type": "gaming mouse"}
    identity, notes = decide(read(visible_text=[], brand=None, model=None), wrong, None, MX)
    assert identity.brand is None and identity.product_name == "gaming mouse"


def test_read_fields_cleans_gemini_output():
    r = read_fields({"category": "  ", "visible_text": ["A", " ", "A", 3], "brand": "  ", "model": "",
                     "attributes": {"Colour": " black ", "x": ""}, "confidence": 7})
    assert r == {"category": "item", "visible_text": ["A"], "attributes": {"colour": "black"}, "brand": None,
                 "model": None, "search_query": None, "confidence": 0.5}


# --- the stage: read and Lens in parallel, then fuse ------------------------------------------------


def fake_stage(monkeypatch, raw, matches, fused=None, lens_error=None):
    calls = {"fuse": 0}

    async def fake_read(views, model=None):
        return GeminiResult(raw=raw, model="fake", latency_ms=1.0, input_tokens=1, output_tokens=1)

    async def fake_lens(views, item_id):
        return matches, ({"error": lens_error} if lens_error else {"matches": len(matches)})

    async def fake_generate(contents, system_prompt, schema, **kwargs):
        calls["fuse"] += 1
        calls["prompt"] = contents
        return GeminiReply(raw=fused or {}, model="fake", latency_ms=1.0)

    monkeypatch.setattr(identify_mod, "call_gemini", fake_read)
    monkeypatch.setattr(identify_mod, "lens_within_budget", fake_lens)
    import gemini
    monkeypatch.setattr(gemini, "generate_json", fake_generate)
    return calls


def ctx_for(tmp_path):
    item = tmp_path / "item"
    item.mkdir()
    return RunContext(item_id="item", item_dir=item, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")


VIEWS = Views(item_id="item", views=[View(view_id="p01", label="photo 1", image_path="p01.jpg")])
RAW = {"category": "wireless mouse", "visible_text": ["MX Master 3S"], "brand": "Logitech", "model": "MX Master 3S",
       "attributes": {}, "search_query": "Logitech MX Master 3S", "confidence": 0.9}


def test_a_read_that_settles_the_model_skips_fuse(tmp_path, monkeypatch):
    calls = fake_stage(monkeypatch, RAW, MX)  # "MX Master 3S" is printed and in the Lens titles
    identity = asyncio.run(identify_mod.identify(ctx_for(tmp_path), VIEWS, None))
    assert identity.product_name == "Logitech MX Master 3S" and calls["fuse"] == 0
    assert identity.search_query == "Logitech MX Master 3S wireless mouse"  # searches keep the product type


def test_stage_fuses_lens_with_the_read(tmp_path, monkeypatch):
    unsure = RAW | {"brand": None, "model": None}  # the photos alone don't name it
    calls = fake_stage(monkeypatch, unsure, MX, fused={"brand": "Logitech", "model": "MX Master 3S",
                                                        "product_type": "wireless mouse"})
    identity = asyncio.run(identify_mod.identify(ctx_for(tmp_path), VIEWS, None))
    assert identity.product_name == "Logitech MX Master 3S" and calls["fuse"] == 1
    assert "- Logitech MX Master 3S Wireless Mouse" in calls["prompt"]
    log = json.loads((tmp_path / "runs" / "identify_raw.json").read_text(encoding="utf-8"))
    assert log["fuse"]["raw"]["model"] == "MX Master 3S" and log["lens"]["matches"] == 4


def test_no_lens_and_no_seller_name_skips_fuse(tmp_path, monkeypatch):
    calls = fake_stage(monkeypatch, RAW, [], lens_error="SERPER_API_KEY is missing")
    identity = asyncio.run(identify_mod.identify(ctx_for(tmp_path), VIEWS, None))
    assert calls["fuse"] == 0
    assert identity.specificity == "type"  # printed model, but nothing else backs the brand


def test_a_failed_fuse_still_identifies_from_the_read(tmp_path, monkeypatch):
    fake_stage(monkeypatch, RAW | {"model": "MX Master 3"}, MX)  # a wrong model guess: the brand still stands

    async def broken(*a, **k):
        raise RuntimeError("429")

    import gemini
    monkeypatch.setattr(gemini, "generate_json", broken)
    identity = asyncio.run(identify_mod.identify(ctx_for(tmp_path), VIEWS, None))
    assert identity.product_name == "Logitech wireless mouse"  # the read's brand, backed by Lens


def test_lens_budget_gives_up_without_failing(monkeypatch):
    import stages.lens as lens_mod

    async def slow(views, item_id):
        await asyncio.sleep(1)

    monkeypatch.setattr(lens_mod, "lens_matches", slow)
    monkeypatch.setitem(IDENTIFY, "lens_budget_s", 0.05)
    matches, log = asyncio.run(identify_mod.lens_within_budget(VIEWS, "item"))
    assert matches == [] and "no Lens answer" in log["error"]


# --- request building and the rest -----------------------------------------------------------------


def test_response_schema_requires_every_field_in_order():
    schema = response_schema()
    assert list(schema["properties"]) == GEMINI["field_order"]
    assert schema["required"] == GEMINI["field_order"]
    assert "default" not in str(schema)


def _png(tmp_path, name, size):
    path = tmp_path / name
    PILImage.new("RGB", size, (128, 128, 128)).save(path, format="PNG")
    return path


def test_contents_interleave_photo_ids_and_images(tmp_path):
    views = Views(item_id="t", views=[
        View(view_id=f"p{i:02d}", label=f"photo {i}", image_path=str(_png(tmp_path, f"p{i}.png", (1024, 1024))))
        for i in range(1, 4)])
    parts, notes = identify_mod.build_contents(views)
    assert len(parts) == 2 * 3 + 1
    assert parts[0].text == "Photo p01:"
    assert parts[1].inline_data.mime_type == "image/png"
    assert notes == []


def test_large_photos_are_shrunk(tmp_path):
    data, mime, note = identify_mod.load_image(_png(tmp_path, "big.png", (4032, 3024)))
    with PILImage.open(io.BytesIO(data)) as img:
        assert max(img.size) == GEMINI["max_side_px"]
    assert "shrunk from 4032x3024" in note


def test_fixture_with_stub_stays_offline(tmp_path, monkeypatch):
    async def no_network(*a, **k):
        raise AssertionError("Gemini called for a fixture with a stub")

    monkeypatch.setattr(identify_mod, "call_gemini", no_network)
    ctx = RunContext(item_id="item01", item_dir=ROOT / "fixtures" / "item01", run_dir=tmp_path, cache_dir=tmp_path)
    identity = asyncio.run(identify_mod.identify(ctx, VIEWS))
    assert identity.product_name == "Sony WH-1000XM4"


def test_missing_key_fails_early(monkeypatch):
    monkeypatch.setattr(identify_mod, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="GEMINI_API_KEY"):
        identify_mod._api_key()


@pytest.mark.parametrize("message, wait", [("429 RESOURCE_EXHAUSTED ... Please retry in 14.04699667s.", 14.04699667),
                                           ("429 ... Please retry in 95s", 20.0), ("429 no hint", 1.0)])
def test_a_429_waits_what_gemini_asks_up_to_a_cap(message, wait):
    class Quota(Exception):
        code = 429

    assert identify_mod.retry_wait_s(Quota(message)) == pytest.approx(wait)
    assert identify_mod.retry_wait_s(ValueError(message)) == 0.0


@pytest.mark.parametrize("name, category, query", [("Lenovo ThinkPad", "wireless mouse", "Lenovo ThinkPad wireless mouse"),
                                                   ("Logitech wireless mouse", "wireless mouse", "Logitech wireless mouse")])
def test_search_queries_keep_the_product_type(name, category, query):
    assert identify_mod.search_query(name, category) == query


@pytest.mark.parametrize("model, ok", [("ThinkPad", False), ("Essential", False), ("MX Master 3S", True),
                                       ("WH-1000XM5", True), ("Magic Mouse", True), ("X1", True)])
def test_one_plain_word_is_not_a_model(model, ok):
    assert identify_mod.specific_enough(model) is ok


def test_a_product_line_is_not_claimed_as_the_model():
    """Live on Supabase scan 2f0f7721: "ThinkPad" was printed, in the seller's name and in Lens titles, so it passed
    as a model; the reference search then found a ThinkPad laptop."""
    r = read(visible_text=["ThinkPad", "Lenovo"], brand="Lenovo", model="ThinkPad")
    identity, notes = decide(r, None, "Lenovo ThinkPad wireless mouse", MOUSE_LENS)
    assert identity.model is None and identity.product_name == "Lenovo wireless mouse"
    assert any("product line" in n for n in notes)
