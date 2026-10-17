"""Create (or replace) the live pipeline's Modal secrets from the repo-root .env, so keys never go in code or chat.

    cp .env.example .env        # in the repo root; fill in the values
    python push_secrets.py      # checks the Supabase key, writes mint-supabase and mint-listing (prints names only)
    modal deploy app.py         # redeploy: the app decides at deploy time which secrets exist
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import modal

ENV = Path(__file__).resolve().parent.parent / ".env"  # the repo-wide .env
SECRETS = {
    "mint-supabase": ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"],
    "mint-listing": ["TYPESAFE_API_KEY", "GEMINI_API_KEY", "SERPER_API_KEY"],
}
OPTIONAL = {"mint-listing": ["GEMINI_MODEL"]}  # copied when set


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("'\"")
    return env


def check_supabase(url: str, key: str) -> str:
    """'ok' if the key can list the project's buckets (what the pipeline needs), else the HTTP problem."""
    req = urllib.request.Request(f"{url.rstrip('/')}/storage/v1/bucket", headers={"apikey": key,
                                                                                  "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            names = {b["name"] for b in json.loads(r.read())}
        missing = {"scans", "assets"} - names
        return f"buckets {sorted(missing)} missing" if missing else "ok"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} (wrong key or URL?)"
    except urllib.error.URLError as e:
        return f"unreachable ({e.reason})"


def main() -> int:
    if not ENV.is_file():
        print(f"no {ENV}: copy .env.example to .env in the repo root and fill it in")
        return 1
    env = read_env(ENV)
    done = 0
    for name, keys in SECRETS.items():
        empty = [k for k in keys if not env.get(k)]
        if empty:
            print(f"{name}: skipped, empty in .env: {', '.join(empty)}")
            continue
        if name == "mint-supabase" and (problem := check_supabase(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])) != "ok":
            print(f"{name}: skipped, Supabase check failed: {problem}")
            continue
        try:
            modal.Secret.objects.delete(name)  # replace, so edited values take effect
        except modal.exception.NotFoundError:
            pass
        keys = keys + [k for k in OPTIONAL.get(name, []) if env.get(k)]
        modal.Secret.objects.create(name, {k: env[k] for k in keys})
        print(f"{name}: set {', '.join(keys)}")
        done += 1
    if done:
        print("now redeploy: modal deploy app.py")
    return 0 if done == len(SECRETS) else 1


if __name__ == "__main__":
    sys.exit(main())
