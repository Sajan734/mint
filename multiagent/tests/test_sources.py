import json
import os

import numpy as np
import pytest

from buyer_agent import sources
from buyer_agent.align import Cloud
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.models import CompareRequest, ViewPair
from tests.test_judge import png, settings

ID = "0b9e6c2a-3f43-4a3e-9a8e-6a1f3b2d9c11"
IMG = frozenset({".png"})


def views_req(path="m.json"):
    return CompareRequest(comparison_id=ID, listing_id="x", view_pairs={"manifest_path": path})


def write_manifest(root, n=12, **over):
    entries = []
    for i in range(n):
        (root / f"a{i}.png").write_bytes(png())
        (root / f"b{i}.png").write_bytes(png())
        entries.append({"label": f"v{i}", "a": f"a{i}.png", "b": f"b{i}.png", **over})
    (root / "m.json").write_text(json.dumps(entries))
    return entries


def code_of(fn, *a):
    with pytest.raises(AgentError) as e:
        fn(*a)
    return e.value.code


def test_absolute_path_rejected(tmp_path):
    for rel in (str(tmp_path / "m.json"), "/m.json", "\\m.json"):
        assert code_of(sources.check_rel, rel, sources.MANIFEST_SUFFIXES) is ErrorCode.INPUT_INVALID


def test_dotdot_rejected(tmp_path):
    for rel in ("../m.json", "a/../m.json", "a\\..\\m.json", "a//m.json"):
        assert code_of(sources.check_rel, rel, sources.MANIFEST_SUFFIXES) is ErrorCode.INPUT_INVALID


@pytest.mark.parametrize(
    "rel",
    [
        "CON.json",
        "nul.json",
        "a:b.json",
        "x.ply:ads",
        "d/com1.json",
        "LPT9",
        "aux.txt.json",
        "con .json",
    ],
)
def test_path_reserved_names(tmp_path, rel):
    assert (
        code_of(sources.safe_open, tmp_path, rel, frozenset({".json", ".ply"}))
        is ErrorCode.INPUT_INVALID
    )


def test_bad_suffix_rejected(tmp_path):
    (tmp_path / "x.exe").write_bytes(b"x")
    assert (
        code_of(sources.safe_open, tmp_path, "x.exe", sources.MANIFEST_SUFFIXES)
        is ErrorCode.INPUT_INVALID
    )


def test_missing_file_is_file_not_found(tmp_path):
    assert (
        code_of(sources.safe_open, tmp_path, "nope.json", sources.MANIFEST_SUFFIXES)
        is ErrorCode.FILE_NOT_FOUND
    )


def test_symlink_escaping_root_rejected(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "out"
    root.mkdir(), outside.mkdir()
    (outside / "s.json").write_text("[]")
    try:
        os.symlink(outside / "s.json", root / "link.json")
    except (OSError, NotImplementedError):
        pytest.skip("no symlink support")
    assert (
        code_of(sources.safe_open, root, "link.json", sources.MANIFEST_SUFFIXES)
        is ErrorCode.INPUT_INVALID
    )


def test_fstat_mismatch_rejected(tmp_path, monkeypatch):
    (tmp_path / "m.json").write_text("[]")
    real = os.fstat
    monkeypatch.setattr(
        os,
        "fstat",
        lambda fd: type(
            "S",
            (),
            {"st_dev": 1, "st_ino": real(fd).st_ino + 1, "st_mode": real(fd).st_mode, "st_size": 2},
        )(),
    )
    assert (
        code_of(sources.safe_open, tmp_path, "m.json", sources.MANIFEST_SUFFIXES)
        is ErrorCode.INPUT_INVALID
    )


def test_views_mode_alignment_skipped(tmp_path):
    write_manifest(tmp_path)
    r = sources.resolve(views_req(), settings(data_root=tmp_path), None)
    assert r.alignment_mode == "skipped_view_pairs" and r.alignment is None and len(r.pairs) == 12


def test_manifest_paths_jailed(tmp_path):
    entries = write_manifest(tmp_path)
    entries[3]["b"] = "../secret.png"
    (tmp_path / "m.json").write_text(json.dumps(entries))
    assert (
        code_of(sources.resolve, views_req(), settings(data_root=tmp_path), None)
        is ErrorCode.INPUT_INVALID
    )


@pytest.mark.parametrize("n", [11, 25])
def test_manifest_pair_count_rejected(tmp_path, n):
    write_manifest(tmp_path, n)
    assert (
        code_of(sources.resolve, views_req(), settings(data_root=tmp_path), None)
        is ErrorCode.INPUT_INVALID
    )


def test_manifest_over_1mb_rejected(tmp_path):
    (tmp_path / "m.json").write_text(" " * (1024 * 1024 + 1))
    assert (
        code_of(sources.resolve, views_req(), settings(data_root=tmp_path), None)
        is ErrorCode.INPUT_INVALID
    )


def test_manifest_duplicate_labels_rejected(tmp_path):
    entries = write_manifest(tmp_path)
    entries[1]["label"] = "v0"
    (tmp_path / "m.json").write_text(json.dumps(entries))
    assert (
        code_of(sources.resolve, views_req(), settings(data_root=tmp_path), None)
        is ErrorCode.INPUT_INVALID
    )


def test_manifest_unknown_field_rejected(tmp_path):
    write_manifest(tmp_path, extra="x")
    assert (
        code_of(sources.resolve, views_req(), settings(data_root=tmp_path), None)
        is ErrorCode.INPUT_INVALID
    )


# ---- splats mode -------------------------------------------------------------------------


class FakeRenderer:
    def __init__(self, calls):
        self.calls = calls

    def render(self, a, b, matrix, crop):
        self.calls.append("render")
        return [ViewPair(label=f"v{i}", png_a=b"a", png_b=b"b") for i in range(12)]


def splat_req():
    ref = {"path": "a.ply", "format": "ply"}
    return CompareRequest(
        comparison_id=ID, listing_id="x", listing_splat=ref, buyer_splat={**ref, "path": "b.ply"}
    )


def patch_splats(monkeypatch, tmp_path, issues):
    calls = []
    cloud = Cloud(np.zeros((3, 3)))
    for n in ("a.ply", "b.ply"):
        (tmp_path / n).write_bytes(b"x")
    monkeypatch.setattr(
        sources.splat_io, "load_cloud", lambda *a, **k: calls.append("load") or cloud
    )
    monkeypatch.setattr(
        sources.quality, "precheck", lambda a, b: calls.append("precheck") or issues
    )
    metrics = {"rmse": 0.1, "a_covered": 0.9, "b_covered": 0.9, "ambiguity": 0.2}
    result = {
        "matrix": np.eye(4).tolist(),
        "scale": 1.0,
        "crop": {"center": [0, 0, 0], "radius": 1},
        "metrics": metrics,
    }
    monkeypatch.setattr(sources.align_mod, "align", lambda a, b: calls.append("align") or result)
    return calls


def test_splats_mode_calls_precheck_align_render_in_order(tmp_path, monkeypatch):
    calls = patch_splats(monkeypatch, tmp_path, [])
    r = sources.resolve(splat_req(), settings(data_root=tmp_path), FakeRenderer(calls))
    assert calls == ["load", "load", "precheck", "align", "render"]
    assert r.alignment_mode == "icp" and r.alignment.scale == 1.0 and len(r.pairs) == 12


def test_precheck_fail_returns_quality_flag(tmp_path, monkeypatch):
    calls = patch_splats(monkeypatch, tmp_path, ["scan_too_sparse_a"])
    r = sources.resolve(splat_req(), settings(data_root=tmp_path), FakeRenderer(calls))
    assert r.quality_issues == ("scan_too_sparse_a",) and r.pairs == [] and "align" not in calls


def test_validate_request_paths_catches_traversal():
    bad = replace_ref("../x.ply")
    assert code_of(sources.validate_request_paths, bad) is ErrorCode.INPUT_INVALID


def replace_ref(path):
    ref = {"path": path, "format": "ply"}
    return CompareRequest(comparison_id=ID, listing_id="x", listing_splat=ref, buyer_splat=ref)
