"""Download every object of every Storage bucket into a local folder (default: ../supabase_clear/, gitignored),
as <bucket>/<path>. Resumable: a file already there with the same size is skipped. Ends by checking that every
object is on disk with its size, and writes inventory.json (bucket, path, size, created_at, mime).

    python supabase_setup/backup.py [out_dir]

Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY: read from the repo-root .env when not already set.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def walk(sb, bucket: str, prefix: str = "") -> list[dict]:
    """Every object under prefix (recursive): {path, size, created_at, mime}."""
    out, offset = [], 0
    while True:
        body = json.dumps({"prefix": prefix, "limit": 1000, "offset": offset,
                           "sortBy": {"column": "name", "order": "asc"}}).encode()
        items = json.loads(sb._req("POST", f"/storage/v1/object/list/{bucket}", body,
                                   {"Content-Type": "application/json"}))
        for i in items:
            path = f"{prefix}/{i['name']}" if prefix else i["name"]
            if i.get("id"):
                meta = i.get("metadata") or {}
                out.append({"path": path, "size": meta.get("size", 0), "created_at": i.get("created_at"),
                            "mime": meta.get("mimetype")})
            else:  # a folder
                out.extend(walk(sb, bucket, path))
        if len(items) < 1000:
            return out
        offset += 1000


def backup(out_dir: Path) -> dict:
    from supabase_setup.storage import Supabase

    sb = Supabase()
    buckets = [b["name"] for b in json.loads(sb._req("GET", "/storage/v1/bucket"))]
    inventory = {b: walk(sb, b) for b in buckets}

    def fetch(job: tuple[str, dict]) -> int:
        bucket, o = job
        dest = out_dir / bucket / o["path"]
        if dest.is_file() and dest.stat().st_size == o["size"]:
            return 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = sb.download(bucket, o["path"])
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return len(data)

    jobs = [(b, o) for b, objs in inventory.items() for o in objs]
    with ThreadPoolExecutor(8) as ex:
        got = sum(ex.map(fetch, jobs))
    missing = [f"{b}/{o['path']}" for b, o in jobs
               if not (out_dir / b / o["path"]).is_file() or (out_dir / b / o["path"]).stat().st_size != o["size"]]
    (out_dir / "inventory.json").write_text(json.dumps(inventory, indent=1), encoding="utf-8")
    summary = {"objects": len(jobs), "mb_total": round(sum(o["size"] for _, o in jobs) / 1e6, 1),
               "mb_downloaded_now": round(got / 1e6, 1), "missing_or_wrong_size": missing,
               "buckets": {b: len(objs) for b, objs in inventory.items()}}
    print(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    from supabase_setup.env import load_env

    load_env()
    backup(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "supabase_clear")
