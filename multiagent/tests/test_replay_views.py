import json

from eval.replay_views import main, replay
from tests.fakes_jev import FakeJev
from tests.test_pipeline import DIFF, ID, go, views


def test_replay_matches_pipeline_verdict(tmp_path, capsys):
    out = go(tmp_path, FakeJev(views(DIFF)))
    folder = tmp_path / "runs" / ID
    v = replay(folder)
    assert (v.label, v.evidence_score) == (out.verdict.label, out.verdict.evidence_score)
    assert main([str(folder)]) == 0
    assert "different" in capsys.readouterr().out


def test_replay_hand_built_folder_and_missing(tmp_path, capsys):
    (tmp_path / "jev").mkdir()
    good = {"viewpoint_match": 0.9, "scan_quality_ok": 0.9, "shape_diff": 0.1, "part_diff": 0.1,
            "color_diff": 0.1, "any_diff": 0.1}  # fmt: skip
    for i in range(8):
        raw = {"view": f"v{i}", "model": "m", "nouls": good, "latency_ms": 1}
        (tmp_path / "jev" / f"view_{i:02d}.json").write_text(json.dumps(raw))
    assert replay(tmp_path).label in {"same", "uncertain"}
    main([str(tmp_path / "nope")])
    assert "cannot replay" in capsys.readouterr().out
