"""app.listing_inputs: what the buyer check gets for each state of the listing. python -m pytest gsplat/tests"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("modal")

from app import listing_inputs  # noqa: E402

MATCH = {"verdict": "match", "reason": "same product"}
MISMATCH = {"verdict": "mismatch", "reason": "a different product"}


class Bucket:
    def __init__(self, files: dict[str, dict]):
        self.files = files

    def download(self, bucket, path, fresh=False):
        if path not in self.files:
            raise RuntimeError(f"Supabase GET {path} -> 400")
        return json.dumps(self.files[path]).encode()


@pytest.mark.parametrize("files,want", [
    ({"listings/L.json": {"status": "listed", "market_listing": {"listing": {"title": "Mouse"}}},
      "listings/L/run/match_gate.json": MATCH}, ({"title": "Mouse"}, MATCH)),
    ({"listings/L.json": {"status": "rejected", "rejection": {"match_check": MISMATCH}}}, (None, MISMATCH)),
    ({"listings/L.json": {"status": "failed", "error": "Gemini 503"}}, (None, None)),
    ({}, (None, None)),  # the listing step has not finished yet
])
def test_listing_inputs(files, want):
    assert listing_inputs(Bucket(files), "L") == want
