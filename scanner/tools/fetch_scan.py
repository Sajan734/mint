#!/usr/bin/env python3
"""Download a scan from Supabase Storage (bucket `scans`) for reconstruction.

  export SUPABASE_URL=https://<ref>.supabase.co
  export SUPABASE_SERVICE_ROLE_KEY=...        # server side only (Modal secret), never in an app
  python3 fetch_scan.py latest  [out_dir]     # newest scan
  python3 fetch_scan.py <scan_id> [out_dir]   # a specific scan (the app shows the id after upload)
  python3 fetch_scan.py list                  # scans, newest first

Standard library only. Files land in out_dir/<scan_id>/ (video.mp4, poses.jsonl, capture.json, thumb.jpg).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = "scans"


def call(path: str, body: dict | None = None) -> bytes:
    req = urllib.request.Request(f"{URL}/storage/v1/{path}", method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {KEY}", "apikey": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.read()


def listing(prefix: str) -> list[dict]:
    return json.loads(call(f"object/list/{BUCKET}", {"prefix": prefix, "limit": 1000, "offset": 0,
                                                       "sortBy": {"column": "name", "order": "asc"}}))


def scans_newest_first() -> list[tuple[str, str]]:
    out = []
    for entry in listing(""):
        if entry.get("id") is not None:  # a file at the top level, not a scan folder
            continue
        files = {f["name"]: f for f in listing(entry["name"] + "/")}
        if "video.mp4" in files:
            out.append((files["video.mp4"].get("created_at") or "", entry["name"]))
    return sorted(out, reverse=True)


def main() -> int:
    if not URL or not KEY:
        sys.exit("set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    what = sys.argv[1] if len(sys.argv) > 1 else "latest"
    if what == "list":
        for created, scan_id in scans_newest_first():
            print(created, scan_id)
        return 0
    scan_id = scans_newest_first()[0][1] if what == "latest" else what
    out = Path(sys.argv[2] if len(sys.argv) > 2 else ".") / scan_id
    out.mkdir(parents=True, exist_ok=True)
    for f in listing(scan_id + "/"):
        data = call(f"object/{BUCKET}/{scan_id}/{f['name']}")
        (out / f["name"]).write_bytes(data)
        print(f"{f['name']:14s} {len(data) / 1e6:6.1f} MB")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
