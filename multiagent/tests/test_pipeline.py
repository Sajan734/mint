import asyncio
import dataclasses
import json
import threading

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


def test_listing_mismatch_is_rejected_without_jev_or_claims(tmp_path):
    jev = FakeJev([])
    claims = ListingClaims(title="Lamp", accessories_included=["charger"])
    check = {"verdict": "mismatch", "reason": "Different product."}
    out = go(tmp_path, jev, req(claims=claims, listing_match_check=check))
    assert out.status == "done" and out.verdict.label == "listing_rejected"
    assert out.next_step.reason_code == "R8" and out.next_step.category == "escalate"
    assert jev.calls == [] and out.claims_findings == [] and not out.claims_available
    assert "repeated" not in out.next_step.summary
    assert "did not compare" in out.explanation.what_we_compared
    assert "could not be compared" not in " ".join(out.explanation.what_we_found)


def test_listing_match_or_uncertain_check_runs_normally(tmp_path):
    check = {"verdict": "uncertain", "reason": "Unsure."}
    out = go(tmp_path, FakeJev(views()), req(listing_match_check=check))
    assert out.verdict.label == "same"


def test_claims_skip_views_the_judge_found_unusable(tmp_path):
    claims = ListingClaims(title="Lamp", accessories_included=["charger"])
    bad = {**GOOD, "viewpoint_match": 0.1}
    jev = FakeJev([*views(bad, 5), *views(GOOD, 7), answer(claim=0.9)])
    out = go(tmp_path, jev, req(claims=claims))
    shown = out.claims_findings[0].views
    assert len(shown) == 4 and not {"v0", "v1", "v2", "v3", "v4"} & set(shown)


def test_slow_claims_degrade_instead_of_failing_the_request(tmp_path):
    class SlowClaims(FakeJev):
        async def ask(self, state, questions, *, key=""):
            if key.startswith("claim"):
                await asyncio.sleep(10)
            return await super().ask(state, questions, key=key)

    claims = ListingClaims(title="Lamp", accessories_included=["charger"])
    out = go(tmp_path, SlowClaims(views()), req(claims=claims), request_cap_s=2, advise_cap_s=1)
    assert out.status == "done" and not out.claims_available
    assert any("could not be checked" in c for c in out.verdict.caveats)
    assert out.next_step is not None


def test_run_log_write_errors_never_fail_a_finished_comparison(tmp_path):
    class BrokenLog(RunLog):
        def save_json(self, name, obj):
            raise OSError("disk full")

        def save_png(self, name, png):
            raise OSError("disk full")

    d = deps(tmp_path, FakeJev(views()))
    d = dataclasses.replace(d, runlog_factory=lambda rid: BrokenLog(tmp_path / "runs", rid))
    out = run(compare(req(), d))
    assert out.status == "done" and out.verdict.label == "same"


def test_oversized_pairs_rejected_before_any_jev_call(tmp_path):
    big = [pair(f"v{i}", a=b"0" * (3 * 1024 * 1024)) for i in range(12)]
    jev = FakeJev([])
    res = lambda r, s, rend: sources.Resolved(big, None, "skipped_view_pairs")
    out = go(tmp_path, jev, resolver=res)
    assert out.status == "failed" and out.error.code == "PAYLOAD_TOO_LARGE"
    assert jev.calls == []


def test_timed_out_resolve_cannot_overlap_the_next_run(tmp_path):
    release, entered = threading.Event(), []

    def slow(r, s, rend):
        entered.append("slow")
        release.wait(3)
        return stub_resolver()(r, s, rend)

    def fast(r, s, rend):
        entered.append(("fast", release.is_set()))
        return stub_resolver()(r, s, rend)

    async def scenario():
        first = await compare(req(), deps(tmp_path, FakeJev([]), resolver=slow, request_cap_s=0.2))
        second = await compare(req(), deps(tmp_path, FakeJev([]), resolver=fast, request_cap_s=0.3))
        release.set()
        return first, second

    first, second = run(scenario())
    assert first.status == "failed" and second.status == "failed"
    assert entered[0] == "slow" and all(flag for name, flag in entered[1:])  # fast waited
