"""listing_text stage: text rules, attributes from the Identity, retry and template fallback. No Gemini calls."""

import asyncio
import json

import pytest

import stages.listing_text as lt
from contracts import Identity, ListingDraft, RunContext
from gemini import GeminiReply
from pipeline import ROOT
from stages.identify import MissingKeyError
from stages.listing_text import TEXT, identity_attributes, response_schema, template_draft, violations

SONY = Identity(
    category="on-ear wireless headphones",
    brand="SONY",
    model="WH-CH510",
    visible_text=["SONY", "WH-CH510", "L", "R"],
    attributes={"colour": "blue", "form_factor": "on-ear"},
    search_query="SONY WH-CH510 blue on-ear wireless headphones",
    confidence=0.9,
)
GENERIC = Identity(
    category="wireless in-ear headphones",
    brand="SONY",
    visible_text=["SONY", "L", "R", "+", "-"],
    attributes={"color": "black"},
    search_query="SONY black wireless in-ear headphones",
    confidence=0.9,
)

CLEAN = {
    "title": "Sony WH-CH510 On-Ear Wireless Headphones (Blue)",
    "description": "SONY WH-CH510 on-ear wireless headphones in blue.",
    "tags": ["Headphones", "sony", "blue", "on-ear", "headphones"],
}


def draft(**overrides):
    return lt.to_draft(CLEAN | overrides, SONY)


def test_schema_asks_only_for_text_fields():
    schema = response_schema()
    assert list(schema["properties"]) == ["title", "description", "tags"]
    assert schema["required"] == ["title", "description", "tags"]


def test_clean_draft_passes_and_tags_are_tidied():
    d = draft()
    assert violations(d, SONY) == []
    assert d.tags == ["headphones", "sony", "blue", "on-ear"]


def test_attributes_come_from_the_identity():
    assert identity_attributes(SONY) == {
        "brand": "SONY", "model": "WH-CH510", "type": "on-ear wireless headphones",
        "colour": "blue", "form_factor": "on-ear",
    }
    assert "model" not in identity_attributes(GENERIC)


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"title": "Sony WH-CH510 " + "x" * 70}, "under 80"),
        ({"description": "Great deal, priced to sell."}, "price"),
        ({"description": "Only $40."}, "price"),
        ({"description": "In excellent condition."}, "condition"),
        ({"description": "Like new, no scratches."}, "condition"),
        ({"description": "Up to 50 hours of battery life."}, "specifications"),
        ({"description": "Has 30mm drivers."}, "specifications"),
        ({"description": "Industry-leading noise cancelling."}, "specifications"),
        ({"title": "Sony WH-CH520 Wireless Headphones"}, "model number"),
        ({"tags": ["headphones", "cheap"]}, "price"),
    ],
)
def test_violations(overrides, expected):
    problems = violations(draft(**overrides), SONY)
    assert any(expected in p for p in problems), problems


def test_title_exactly_at_the_limit_fails():
    title = "SONY WH-CH510 on-ear wireless headphones in blue, " + "x" * 30
    assert len(title) == TEXT["title_limit_chars"]
    assert violations(draft(title=title), SONY)
    assert not violations(draft(title=title[:-1]), SONY)


def test_model_guess_flagged_when_identity_has_no_model():
    d = lt.to_draft({"title": "Sony WI-C200 Wireless Earbuds", "description": "Black wireless earbuds.", "tags": []}, GENERIC)
    assert any("WI-C200" in p for p in violations(d, GENERIC))


def test_identity_values_are_not_flagged():
    identity = SONY.model_copy(update={"attributes": {"finish": "mint green"}})
    d = lt.to_draft(CLEAN | {"description": "SONY WH-CH510 headphones in mint green."}, identity)
    assert violations(d, identity) == []


def test_template_draft_is_clean_and_short():
    for identity in (SONY, GENERIC):
        d = template_draft(identity)
        assert violations(d, identity) == []
        assert len(d.title) < TEXT["title_limit_chars"]
    assert template_draft(SONY).title == "SONY WH-CH510 on-ear wireless headphones (blue)"
    long = SONY.model_copy(update={"category": "lightweight foldable on-ear wireless headphones with microphone and case"})
    assert len(template_draft(long).title) < TEXT["title_limit_chars"]


def fake_gemini(monkeypatch, answers):
    calls = []

    async def fake(contents, system_prompt, schema, **kwargs):
        calls.append(contents)
        answer = answers[len(calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return GeminiReply(raw=answer, model="fake", latency_ms=1.0)

    monkeypatch.setattr(lt, "generate_json", fake)
    return calls


def ctx_for(tmp_path):
    item_dir = tmp_path / "item"
    item_dir.mkdir()
    return RunContext(item_id="item", item_dir=item_dir, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")


def test_clean_answer_used_and_logged(tmp_path, monkeypatch):
    calls = fake_gemini(monkeypatch, [CLEAN])
    result = asyncio.run(lt.listing_text(ctx_for(tmp_path), SONY))
    assert result.title == CLEAN["title"] and result.attributes == identity_attributes(SONY)
    assert len(calls) == 1
    log = json.loads((tmp_path / "runs" / "listing_text_raw.json").read_text())
    assert log["source"] == "gemini"


def test_retry_fixes_a_problem(tmp_path, monkeypatch):
    calls = fake_gemini(monkeypatch, [CLEAN | {"description": "Like new."}, CLEAN])
    result = asyncio.run(lt.listing_text(ctx_for(tmp_path), SONY))
    assert result.description == CLEAN["description"]
    assert len(calls) == 2 and "mentions condition" in calls[1]


def test_template_after_two_bad_answers(tmp_path, monkeypatch):
    bad = CLEAN | {"description": "Great price."}
    fake_gemini(monkeypatch, [bad, bad])
    result = asyncio.run(lt.listing_text(ctx_for(tmp_path), SONY))
    assert result == template_draft(SONY)
    log = json.loads((tmp_path / "runs" / "listing_text_raw.json").read_text())
    assert log["source"] == "template" and len(log["attempts"]) == 2


def test_template_when_gemini_fails(tmp_path, monkeypatch):
    fake_gemini(monkeypatch, [RuntimeError("503 UNAVAILABLE")])
    assert asyncio.run(lt.listing_text(ctx_for(tmp_path), SONY)) == template_draft(SONY)


def test_missing_key_still_raises(tmp_path, monkeypatch):
    fake_gemini(monkeypatch, [MissingKeyError("GEMINI_API_KEY is missing")])
    with pytest.raises(MissingKeyError):
        asyncio.run(lt.listing_text(ctx_for(tmp_path), SONY))


def test_fixture_stub_used_without_calling_gemini(tmp_path, monkeypatch):
    fake_gemini(monkeypatch, [])
    item_dir = ROOT / "fixtures" / "item01"
    ctx = RunContext(item_id="item01", item_dir=item_dir, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    result = asyncio.run(lt.listing_text(ctx, SONY))
    assert result == ListingDraft.model_validate_json((item_dir / "stubs" / "listing_text.json").read_text())


def test_a_slow_gemini_gives_the_template_within_the_budget(tmp_path, monkeypatch):
    from contracts import Identity

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(lt, "generate_json", slow)
    monkeypatch.setitem(TEXT, "budget_s", 0.05)
    identity = Identity(category="wireless mouse", brand="ThinkPad", visible_text=["ThinkPad"],
                        search_query="ThinkPad wireless mouse", confidence=0.9)
    item_dir = tmp_path / "item"
    item_dir.mkdir()
    ctx = RunContext(item_id="item", item_dir=item_dir, run_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    draft = asyncio.run(lt.listing_text(ctx, identity))
    assert draft == template_draft(identity)
    log = json.loads((tmp_path / "runs" / "listing_text_raw.json").read_text(encoding="utf-8"))
    assert log["source"] == "template" and "within" in log["error"]
