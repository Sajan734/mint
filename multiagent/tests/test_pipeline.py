import json

from buyer_agent import sources
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.groq_client import GroqAnswer, GroqCallError
from buyer_agent.models import CompareRequest, ListingClaims
from buyer_agent.pipeline import UNVALIDATED_CAVEAT, Deps, compare
from buyer_agent.runlog import RunLog, register_secrets
from tests.fakes_groq import FakeGroq
from tests.fakes_jev import FakeJev, answer
from tests.test_judge import GOOD, pair, png, run, settings

ID = "0b9e6c2a-3f43-4a3e-9a8e-6a1f3b2d9c11"
DIFF = {**GOOD, "part_diff": 0.68}


def req(**kw):
    base = {"comparison_id": ID, "listing_id": "x", "view_pairs": {"manifest_path": "m.json"}}
    return CompareRequest(**{**base, **kw})


def splat_req(**kw):
    ref = {"path": "a.ply", "format": "ply"}
    return req(view_pairs=None, listing_splat=ref, buyer_splat=ref, **kw)


def stub_resolver(mode="skipped_view_pairs", issues=()):
    pairs = [] if issues else [pair(f"v{i}") for i in range(12)]
    return lambda r, s, rend: sources.Resolved(pairs, None, mode, tuple(issues))


def deps(tmp_path, jev, groq=None, resolver=None, **st):
    return Deps(
        settings=settings(runs_root=tmp_path / "runs", data_root=tmp_path, **st),
        jev=jev, groq=groq or FakeGroq([GroqCallError(False, "down")]), renderer=None,
        runlog_factory=lambda rid: RunLog(tmp_path / "runs", rid),
        resolver=resolver or stub_resolver(),
    )  # fmt: skip


def views(scores=GOOD, n=12):
    return [answer(**scores) for _ in range(n)]


def go(tmp_path, jev, r=None, **kw):
    return run(compare(r or req(), deps(tmp_path, jev, **kw)))


def test_happy_path_done_with_next_step(tmp_path):
    out = go(tmp_path, FakeJev(views()))
    assert out.status == "done" and out.verdict.label == "same"
    assert out.next_step.category == "none" and out.next_step.is_template
    assert set(out.timings_ms) >= {"resolve", "judge", "claims", "advise", "total"}
    assert any("No listing details" in c for c in out.verdict.caveats) and not out.claims_available


def test_jev_unavailable_gives_failed_no_plan(tmp_path):
    jev = FakeJev([AgentError(ErrorCode.JEV_TIMEOUT)] * 12)
    out = go(tmp_path, jev)
    assert out.status == "failed" and out.next_step is None and out.verdict is None
    assert out.error.code == "JEV_UNAVAILABLE" and "try again" in out.error.message
    assert not (tmp_path / "runs" / ID / "response.json").exists()


def test_scan_quality_poor_routes_to_r1(tmp_path):
    jev = FakeJev([])
    out = go(tmp_path, jev, splat_req(), resolver=stub_resolver("icp", ["scan_too_sparse_a"]))
    assert out.verdict.label == "scan_quality_poor" and out.next_step.reason_code == "R1"
    assert jev.calls == []


def test_claims_unavailable_still_done_with_caveat(tmp_path):
    claims = ListingClaims(title="Lamp", accessories_included=["charger"])
    jev = FakeJev([*views(), RuntimeError("boom")])
    out = go(tmp_path, jev, req(claims=claims))
    assert out.status == "done"
    assert out.claims_findings[0].status == "unverifiable"


def test_groq_down_template_response_valid(tmp_path):
    out = go(tmp_path, FakeJev(views(DIFF)), groq=FakeGroq([GroqCallError(False, "x")]))
    assert (
        out.status == "done"
        and out.next_step.is_template
        and out.next_step.drafted_by == "template"
    )


def test_planner_reads_pre_claims_score(tmp_path):
    claims = ListingClaims(title="Lamp", accessories_included=["charger"])
    out = go(tmp_path, FakeJev([*views(DIFF), answer(claim=0.1)]), req(claims=claims))
    assert out.claims_findings[0].status == "contradicted"
    assert out.next_step.reason_code == "R5" and out.verdict.evidence_score == 0.68


def test_unvalidated_renderer_caveat_in_splats_mode(tmp_path):
    out = go(tmp_path, FakeJev(views()), splat_req(), resolver=stub_resolver("icp"))
    assert UNVALIDATED_CAVEAT in out.verdict.caveats
    ok = go(tmp_path / "b", FakeJev(views()), splat_req(), resolver=stub_resolver("icp"),
            renderer_validated=True)  # fmt: skip
    assert UNVALIDATED_CAVEAT not in ok.verdict.caveats


def test_alignment_skipped_caveat_in_views_mode(tmp_path):
    out = go(tmp_path, FakeJev(views()))
    assert any("not aligned by us" in c for c in out.verdict.caveats)
    assert UNVALIDATED_CAVEAT not in out.verdict.caveats


def test_run_folder_has_request_pngs_jev_groq_response(tmp_path):
    go(tmp_path, FakeJev(views()))
    folder = tmp_path / "runs" / ID
    names = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert {"request.json", "a_00.png", "b_11.png", "jev/view_00.json", "groq.json",
            "response.json"} <= names  # fmt: skip


def test_no_secret_in_any_saved_file(tmp_path):
    secret = "typesafe-SUPERSECRET123"
    register_secrets(secret)
    out = go(tmp_path, FakeJev(views()), req(claims=ListingClaims(title=secret)))
    assert out.status == "done"
    for p in (tmp_path / "runs").rglob("*.json"):
        assert secret not in p.read_text(encoding="utf-8")


def test_end_to_end_views_mode_with_generated_pngs(tmp_path):
    entries = []
    for i in range(12):
        for side in "ab":
            (tmp_path / f"{side}{i}.png").write_bytes(png(color=(10 * i, 40, 90)))
        entries.append({"label": f"v{i}", "a": f"a{i}.png", "b": f"b{i}.png"})
    (tmp_path / "m.json").write_text(json.dumps(entries))
    text = json.dumps(
        {"summary": "Nothing differs between the two scans.", "message_to_seller": None,
         "refund_request": None, "cited_views": []}
    )  # fmt: skip
    groq = FakeGroq([GroqAnswer("openai/gpt-oss-120b", text)])
    d = deps(tmp_path, FakeJev(views()), groq, resolver=sources.resolve)
    out = run(compare(req(), d))
    assert out.status == "done" and out.verdict.label == "same"
    assert out.verdict.evidence.alignment_mode == "skipped_view_pairs"
    assert out.next_step.category == "none" and len(groq.calls) >= 1
    assert RunLog(tmp_path / "runs", ID).load_response().status == "done"
