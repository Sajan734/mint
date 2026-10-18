"""Storage-mode publishing against an in-memory bucket: python -m pytest gsplat/tests"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mintsplat import publish as pub  # noqa: E402


class FakeStorage:
    """The supabase_setup.storage.Supabase methods publish.py uses; newest object first, like Supabase."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}  # "bucket/path" -> bytes, in upload order

    def upload(self, bucket, path, data, content_type, cache_control="max-age=3600"):
        self.objects.pop(f"{bucket}/{path}", None)
        self.objects[f"{bucket}/{path}"] = data
        return self.public_url(bucket, path)

    def public_url(self, bucket, path):
        return f"https://x/{bucket}/{path}"

    def list_objects(self, bucket, folder, limit=1000):
        prefix = f"{bucket}/{folder.rstrip('/')}/"
        names = [k[len(prefix):] for k in self.objects if k.startswith(prefix)]
        return [{"name": n, "id": n, "created_at": None} for n in reversed(names) if "/" not in n]

    def list(self, bucket, folder):
        return [o["name"] for o in self.list_objects(bucket, folder)]


def result():
    held = {"items": [{"file": "00.jpg"}]}
    return {"files": {"splat.spz": b"spz", "heldout/heldout.json": json.dumps(held).encode(), "heldout/00.jpg": b"j"},
            "coverage": "top", "passes": 1, "gaussians": {"after": 1}, "sizes_mb": {}, "timings": {}}


def indexed(sb):
    return [s["scan_id"] for s in json.loads(sb.objects["assets/splats/index.json"])["scans"]]


def test_rescan_stays_out_of_the_index_after_a_later_scan():
    sb = FakeStorage()
    pub.publish(sb, "listing1", "listing1", ["video.mp4"], result(), {})
    pub.publish(sb, "rescan1", "rescan1", ["rescan.mp4"], result(), {}, index=False)
    pub.publish(sb, "listing2", "listing2", ["video.mp4"], result(), {})
    assert indexed(sb) == ["listing2", "listing1"]
    assert "assets/splats/rescan1.json" in sb.objects  # the check page still finds the buyer's splat
