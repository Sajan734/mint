import json

from buyer_agent.config import JEV_MODEL_PIN
from eval.ci_check import bad_fixtures, main


def put(root, name, obj):
    p = root / "tests" / "fixtures" / "replay" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))
    return p


def test_ci_check_refuses_fixture_with_wrong_model(tmp_path, caplog):
    bad = put(tmp_path, "bad.json", [{"x": {"model": "jev-1.12.0"}}])
    put(tmp_path, "ok.json", {"model": JEV_MODEL_PIN})
    assert bad_fixtures(tmp_path) == [bad]
    assert main(root=tmp_path, run_tests=False) == 1
    assert str(bad) in caplog.text


def test_ci_check_passes_on_pinned_fixtures(tmp_path):
    put(tmp_path, "ok.json", {"records": [{"model": JEV_MODEL_PIN}]})
    assert main(root=tmp_path, run_tests=False) == 0
    assert main(root=tmp_path / "nothing", run_tests=False) == 0
