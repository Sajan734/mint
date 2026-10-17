import pytest

from buyer_agent import modal_render as mr
from buyer_agent.errors import AgentError


def test_pairs_use_identical_args_and_unique_labels():
    calls = []

    def fake(ply, up, angles, size, bg):
        calls.append((ply, up, angles, size, bg))
        return [ply + bytes([i]) for i in range(len(angles))]

    pairs = mr.render_pairs(b"A", b"B", "+z", call=fake)
    assert len(pairs) == 12 and len({p.label for p in pairs}) == 12
    assert all(len(p.label) < 80 for p in pairs)
    assert calls[0][1:] == calls[1][1:] == ("+z", mr.ANGLES, 1024, (128, 128, 128))
    assert pairs[1].png_a == b"A\x01" and pairs[1].png_b == b"B\x01"


def test_wrong_count_rejected():
    with pytest.raises(AgentError):
        mr.render_pairs(b"A", b"B", call=lambda *a: [b"x"])


def test_missing_modal_is_clean_error():
    with pytest.raises(AgentError):
        mr.modal_call(b"", "-y", [], 1, (0, 0, 0))
