import json

import pytest

from buyer_agent.aggregate import Thresholds
from buyer_agent.groq_client import GroqCallError
from eval.prereg import PreregMismatch, render_prereg
from eval.run_eval import (
    EvalError,
    RunResult,
    build_request,
    classify,
    load_cases,
    run_eval,
    summarise,
)
from tests.fakes_groq import FakeGroq
from tests.fakes_jev import FakeJev, answer
from tests.test_judge import GOOD, run, settings
from tests.test_pipeline import DIFF, stub_resolver

CASES = [
    {"case": "pots_same", "split": "heldout", "scene": "Pots", "mode": "views",
     "manifest": "m.json", "claims": None, "expected_label": "same",
     "acceptable": ["same"], "wrong": ["different"]},
    {"case": "pots_changed", "split": "heldout", "scene": "Pots", "mode": "views",
     "manifest": "m2.json", "claims": None, "expected_label": "different",
     "acceptable": ["different"], "wrong": ["same"]},
]  # fmt: skip
VIEWS = 12


def write_files(tmp_path, cases=CASES):
    text = render_prereg().replace(
        "```json cases\n[]\n```", f"```json cases\n{json.dumps(cases)}\n```"
    )
    pre, exp = tmp_path / "PREREG.md", tmp_path / "expected.json"
    pre.write_text(text, encoding="utf-8")
    exp.write_text(json.dumps(cases), encoding="utf-8")
    return pre, exp


def jev_for(*per_case):
    """Scripted answers: one block of VIEWS per (case, run)."""
    return FakeJev([answer(**s) for s in per_case for _ in range(VIEWS)])


def go(tmp_path, jev, pre, exp, **kw):
    st = settings(runs_root=tmp_path / "runs", data_root=tmp_path)
    return run(
        run_eval("heldout", st, jev, FakeGroq([GroqCallError(False, "x")] * 40), None,
                 prereg_path=pre, expected_path=exp, commit_of=lambda p: "abc123",
                 resolver=stub_resolver(), **kw)
    )  # fmt: skip


def test_empty_cases_template_refuses_clearly(tmp_path):
    pre, exp = write_files(tmp_path, cases=[])
    with pytest.raises(EvalError, match="empty"):
        load_cases("tune", pre, exp)


def test_unreadable_prereg_refuses(tmp_path):
    bad = tmp_path / "PREREG.md"
    bad.write_text("# nothing here")
    with pytest.raises(EvalError, match="cannot read"):
        load_cases("tune", bad, tmp_path / "expected.json")


def test_missing_expected_json_refuses(tmp_path):
    pre, _ = write_files(tmp_path)
    with pytest.raises(EvalError, match="nope.json"):
        load_cases("heldout", pre, tmp_path / "nope.json")


def test_expected_json_disagreement_refuses(tmp_path):
    pre, exp = write_files(tmp_path)
    bad = [{**CASES[0], "expected_label": "different"}, CASES[1]]
    exp.write_text(json.dumps(bad))
    with pytest.raises(EvalError, match="disagrees"):
        load_cases("heldout", pre, exp)


def test_unknown_split_refuses(tmp_path):
    pre, exp = write_files(tmp_path)
    with pytest.raises(EvalError, match="no pre-registered cases"):
        load_cases("tune", pre, exp)


def test_classify():
    assert classify(CASES[0], "different") == "wrong"
    assert classify(CASES[1], "different") == "ok"
    assert classify(CASES[0], "failed") == "other"


def test_build_request_modes_and_deterministic_id(tmp_path):
    a, b = build_request(CASES[0], 1, tmp_path), build_request(CASES[0], 1, tmp_path)
    assert a.comparison_id == b.comparison_id != build_request(CASES[0], 2, tmp_path).comparison_id
    ref = {"path": "a.ply", "format": "ply"}
    sp = build_request(
        {**CASES[0], "mode": "splats", "listing_splat": ref, "buyer_splat": ref}, 1, tmp_path
    )
    assert sp.view_pairs is None
    with pytest.raises(EvalError):
        build_request({**CASES[0], "mode": "x"}, 1, tmp_path)


def test_summarise_counts_false_same_and_pin():
    rr = lambda lab, out: RunResult(1, lab, out, "jev-1.13.0", 0.1)
    runs = [
        [rr("same", "ok")] * 3,
        [rr("same", "wrong"), rr("different", "ok"), rr("same", "wrong")],
    ]
    rep = summarise(CASES, runs)
    assert rep["false_same_on_changed"]["k"] == 2 and rep["false_same_on_changed"]["n"] == 3
    assert rep["s2_pass"] is False and rep["model_pin_ok"] is True
    assert rep["class_counts"] == {"different": 1, "same": 5}
    assert rep["false_same_on_changed"]["per_run_spread"][2] == 1.0


def test_summarise_flags_wrong_model():
    r = RunResult(1, "same", "ok", "jev-9", None)
    assert summarise(CASES[:1], [[r]])["model_pin_ok"] is False


def test_run_eval_end_to_end_with_fakes(tmp_path):
    pre, exp = write_files(tmp_path)
    jev = jev_for(*([GOOD] * 3 + [DIFF] * 3))  # case-major: 3 runs of same, then of changed
    rep = go(tmp_path, jev, pre, exp)
    assert rep["n_cases"] == 2 and rep["n_runs"] == 3 and len(jev.calls) == VIEWS * 6
    assert rep["s2_pass"] and rep["false_same_on_changed"]["k"] == 0
    assert rep["prereg_commit"] == "abc123" and len(rep["cases_sha256"]) == 64
    assert rep["model_pin_ok"] and any("photos" in c for c in rep["caveats"])
    assert any("unvalidated" in c for c in rep["caveats"])
    assert set(rep["results"]) == {"pots_same", "pots_changed"}


def test_run_eval_reports_false_same_on_changed(tmp_path):
    pre, exp = write_files(tmp_path)
    jev = jev_for(*([GOOD] * 6))  # changed case wrongly called same, every run
    rep = go(tmp_path, jev, pre, exp)
    assert rep["false_same_on_changed"]["k"] == 3 and not rep["s2_pass"]
    assert rep["false_same_on_changed"]["wilson95"][0] > 0.4


def test_run_eval_refuses_changed_thresholds(tmp_path, monkeypatch):
    pre, exp = write_files(tmp_path)
    monkeypatch.setattr("eval.run_eval.Thresholds", lambda: Thresholds(match_min=0.6))
    with pytest.raises(PreregMismatch):
        go(tmp_path, FakeJev([]), pre, exp)
