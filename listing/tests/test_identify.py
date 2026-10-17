"""identify stage: evidence rule, request building, offline fixture path. No Gemini calls."""

import asyncio
import io

import pytest
from PIL import Image as PILImage

import stages.identify as identify_mod
from contracts import Identity, RunContext, View, Views
from pipeline import ROOT
from stages.identify import GEMINI, MissingKeyError, enforce_evidence, response_schema, to_identity


def raw(**overrides):
    base = {
        "category": "over-ear wireless headphones",
        "visible_text": ["SONY", "WH-1000XM4"],
        "brand": "Sony",
        "model": "WH-1000XM4",
        "attributes": {"Colour": "black"},
        "search_query": "Sony WH-1000XM4 black",
        "confidence": 0.9,
    }
    return base | overrides


def test_backed_brand_and_model_kept():
    identity, notes = to_identity(raw())
    assert (identity.brand, identity.model) == ("Sony", "WH-1000XM4")
    assert identity.search_query == "Sony WH-1000XM4 black"
    assert identity.attributes == {"colour": "black"}
    assert notes == []


def test_unbacked_brand_and_guessed_model_become_null():
    identity, notes = to_identity(raw(visible_text=[]))
    assert identity.brand is None and identity.model is None
    assert identity.search_query == "black over-ear wireless headphones"
    assert any("dropped brand" in n for n in notes) and any("dropped model" in n for n in notes)


def test_query_guess_removed_when_gemini_nulls_brand_itself():
    # Seen live: brand and model null, but the query still named a guessed product.
    identity, notes = to_identity(
        raw(brand=None, model=None, visible_text=["L", "R"], search_query="Sony WI-C200 black wireless in-ear headphones")
    )
    assert "Sony" not in identity.search_query and "WI-C200" not in identity.search_query
    assert identity.search_query == "black over-ear wireless headphones"
    assert any("search_query rebuilt" in n for n in notes)


def test_model_recognised_from_design_only_becomes_null():
    # Seen live: SONY legible, no model text, Gemini named the wrong model (WI-C200) at 0.95.
    identity, notes = to_identity(raw(model="WI-C200", visible_text=["SONY", "L", "R"]))
    assert identity.brand == "Sony"
    assert identity.model is None
    assert identity.search_query == "Sony black over-ear wireless headphones"
    assert any("dropped model 'WI-C200'" in n for n in notes)


def test_contract_rejects_unbacked_model():
    with pytest.raises(ValueError, match="model 'WI-C200' is not backed"):
        Identity(category="earphones", brand="Sony", model="WI-C200", visible_text=["SONY"],
                 search_query="q", confidence=0.9)


def test_model_kept_when_its_own_text_is_visible():
    identity, _ = to_identity(raw(visible_text=["WH-1000XM4"]))
    assert identity.brand is None
    assert identity.model == "WH-1000XM4"


def test_brand_backing_ignores_case_and_punctuation():
    identity, notes = to_identity(raw(brand="Bang & Olufsen", model=None, visible_text=["BANG&OLUFSEN"]))
    assert identity.brand == "Bang & Olufsen"
    assert not any(n.startswith("dropped") for n in notes)


def test_brand_model_given_without_brand_is_dropped():
    identity, _ = to_identity(raw(brand=None, visible_text=["noise cancelling"]))
    assert identity.model is None


def test_blank_strings_and_extra_fields_cleaned():
    fields, notes = enforce_evidence(raw(brand="  ", model="", search_query=" ", surprise=1))
    assert fields["brand"] is None and fields["model"] is None
    assert fields["search_query"] == "black over-ear wireless headphones"
    assert "surprise" not in fields and any("unexpected" in n for n in notes)
    Identity.model_validate(fields)


def test_response_schema_requires_every_field_in_order():
    schema = response_schema()
    assert list(schema["properties"]) == GEMINI["field_order"]
    assert schema["required"] == GEMINI["field_order"]
    assert "default" not in str(schema)


def _png(tmp_path, name, size):
    path = tmp_path / name
    PILImage.new("RGB", size, (128, 128, 128)).save(path, format="PNG")
    return path


def test_contents_interleave_labels_and_images(tmp_path):
    views = Views(
        item_id="t",
        views=[
            View(view_id=f"v{i:02d}", label=f"label {i}", azimuth_deg=0, elevation_deg=10,
                 image_path=str(_png(tmp_path, f"v{i}.png", (1024, 1024))))
            for i in range(3)
        ],
    )
    parts, notes = identify_mod.build_contents(views)
    assert len(parts) == 2 * 3 + 1
    assert parts[0].text == "View v00: label 0"
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
    identity = asyncio.run(identify_mod.identify(ctx, Views(item_id="item01", views=[
        View(view_id="v00", label="x", azimuth_deg=0, elevation_deg=10, image_path="missing.png")])))
    assert identity.brand == "Sony"


def test_missing_key_fails_early(monkeypatch):
    monkeypatch.setattr(identify_mod, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="GEMINI_API_KEY"):
        identify_mod._api_key()
