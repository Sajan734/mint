"""Small CPU-only Modal app around the shared Supabase layer (no GPU, starts in ~1-2 s).

    modal run supabase_setup/modal_app.py      # smoke test: secret, buckets, signed upload, realtime
    modal deploy supabase_setup/modal_app.py   # makes sign_uploads callable by other apps / clients

Needs the Modal secret `mint-supabase` (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).
"""
import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, so `supabase_setup` imports

secret = modal.Secret.from_name("mint-supabase", required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
image = modal.Image.debian_slim(python_version="3.11").add_local_python_source("supabase_setup")
app = modal.App("mint-supabase", image=image)


@app.function(secrets=[secret], timeout=60)
def sign_uploads(scan_id: str, names: list[str]) -> dict[str, str]:
    """Signed upload URLs for scans/{scan_id}/{name}. This is what mint-api's POST /scans hands the iOS
    app: the phone uploads straight to Storage, holds no key, and the bytes never pass through a function."""
    from supabase_setup.storage import SCANS, Supabase

    sb = Supabase()
    return {n: sb.signed_upload_url(SCANS, f"{scan_id}/{n}") for n in names}


@app.function(secrets=[secret], timeout=120)
def smoke_test() -> dict:
    """End-to-end check of the setup, timing each call. Writes and reads one small file in `fixtures`."""
    import json
    import time
    import urllib.request

    from supabase_setup.storage import ASSETS, SCANS, Supabase, new_id

    sb = Supabase()
    t, out = time.perf_counter, {}
    run_id = new_id()

    def reachable(bucket: str) -> bool:
        try:
            sb.list(bucket, "")
            return True
        except RuntimeError as e:
            print(e)
            return False

    t0 = t()
    out["buckets_reachable"] = {b: reachable(b) for b in (SCANS, ASSETS, "fixtures")}
    out["list_s"] = round(t() - t0, 3)

    payload = json.dumps({"run_id": run_id}).encode()
    t0 = t()
    sb.upload("fixtures", f"smoke/{run_id}.json", payload, "application/json")
    out["upload_s"] = round(t() - t0, 3)
    t0 = t()
    out["download_ok"] = sb.download("fixtures", f"smoke/{run_id}.json") == payload
    out["download_s"] = round(t() - t0, 3)

    t0 = t()
    url = sb.signed_upload_url(SCANS, f"smoke-{run_id}/top.txt")
    req = urllib.request.Request(url, data=b"signed upload ok", method="PUT", headers={"Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    out["signed_upload_ok"] = sb.download(SCANS, f"smoke-{run_id}/top.txt") == b"signed upload ok"
    out["signed_upload_s"] = round(t() - t0, 3)

    t0 = t()
    sb.broadcast(run_id, "stage", {"stage": "smoke_test", "status": "done", "ms": 0})
    out["broadcast_s"] = round(t() - t0, 3)
    out["public_url_example"] = sb.public_url(ASSETS, "splats/<scan_id>.spz")
    return out


@app.local_entrypoint()
def main():
    import json

    print(json.dumps(smoke_test.remote(), indent=2))
