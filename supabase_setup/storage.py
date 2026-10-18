"""Minimal Supabase client (Storage + Realtime broadcast) over plain HTTPS.

Runs inside Modal (and backup.py): the service-role key (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) comes from
the repo-root .env, which `modal deploy` sends with the app, and never leaves the backend. Clients (the iOS app,
client.py) only ever see short-lived signed upload URLs.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

SCANS, ASSETS = "scans", "assets"  # private videos / public outputs (Supabase reserves "public")


class Supabase:
    def __init__(self):
        if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set: put them in the repo-root "
                               ".env, then redeploy (see supabase_setup/README.md)")
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self._auth = {"apikey": key, "Authorization": f"Bearer {key}"}

    def _req(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> bytes:
        """Every failure is a RuntimeError (callers catch that one type, e.g. for "not there yet"). A dropped
        connection, a timeout or a 5xx is tried once more: every request here is safe to repeat (uploads upsert)."""
        for attempt in range(2):
            req = urllib.request.Request(self.url + path, data=body, method=method,
                                         headers={**self._auth, **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt:
                    raise RuntimeError(f"Supabase {method} {path} -> {e.code}: {e.read()[:300]!r}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt:
                    raise RuntimeError(f"Supabase {method} {path} -> {type(e).__name__}: {e}") from None
            time.sleep(1.0)
        raise AssertionError("unreachable")

    # ---- storage
    def download(self, bucket: str, path: str, fresh: bool = False) -> bytes:
        """fresh: bypass caches with a unique query string. Use it for objects that are overwritten in place
        (listing documents): a plain read straight after a write has returned the previous copy."""
        query = f"?t={time.time_ns()}" if fresh else ""
        return self._req("GET", f"/storage/v1/object/authenticated/{bucket}/{path}{query}")

    def list_objects(self, bucket: str, folder: str, limit: int = 1000) -> list[dict]:
        """Files directly inside `folder`, newest first: dicts with name, created_at, updated_at, metadata."""
        body = json.dumps({"prefix": folder.rstrip("/"), "limit": limit,
                           "sortBy": {"column": "created_at", "order": "desc"}}).encode()
        items = json.loads(self._req("POST", f"/storage/v1/object/list/{bucket}", body,
                                     {"Content-Type": "application/json"}))
        return [i for i in items if i.get("id")]  # folders have no id

    def list(self, bucket: str, folder: str) -> list[str]:
        """File names directly inside `folder`."""
        return [i["name"] for i in self.list_objects(bucket, folder)]

    def upload(self, bucket: str, path: str, data: bytes, content_type: str,
               cache_control: str = "max-age=3600") -> str:
        """Upsert one object; returns its public URL (meaningful for public buckets). Use cache_control="no-cache"
        for objects that are overwritten in place (indexes), so the CDN doesn't serve a stale copy."""
        self._req("POST", f"/storage/v1/object/{bucket}/{path}", data,
                  {"Content-Type": content_type, "x-upsert": "true", "Cache-Control": cache_control})
        return self.public_url(bucket, path)

    def public_url(self, bucket: str, path: str) -> str:
        return f"{self.url}/storage/v1/object/public/{bucket}/{path}"

    def signed_upload_url(self, bucket: str, path: str) -> str:
        """URL a client can PUT one file to without any key (valid ~2 h, Supabase default)."""
        r = json.loads(self._req("POST", f"/storage/v1/object/upload/sign/{bucket}/{path}", b"{}",
                                 {"Content-Type": "application/json", "x-upsert": "true"}))
        return f"{self.url}/storage/v1{r['url']}"

    # ---- realtime
    def broadcast(self, channel_id: str, type_: str, payload: dict, t_ms: int = 0) -> None:
        """Envelope from contracts/realtime_event.schema.json on channel `batch:{channel_id}`."""
        env = {"v": 3, "type": type_, "id": channel_id, "at": datetime.now(timezone.utc).isoformat(),
               "t_ms": int(t_ms), "payload": payload}
        body = json.dumps({"messages": [{"topic": f"batch:{channel_id}", "event": type_, "payload": env,
                                         "private": False}]}).encode()
        try:
            self._req("POST", "/realtime/v1/api/broadcast", body, {"Content-Type": "application/json"})
        except RuntimeError as e:  # events are for live UI; never fail a scan over one
            print(f"broadcast failed: {e}", flush=True)


class Events:
    """Fire-and-forget, in-order realtime events from a background thread (each broadcast is an HTTP
    round trip; inline they would add ~2 s to a scan)."""

    def __init__(self, sb: Supabase, channel_id: str):
        from concurrent.futures import ThreadPoolExecutor
        import time

        self.sb, self.channel_id, self._t0 = sb, channel_id, time.perf_counter()
        self._clock = time.perf_counter
        self._ex = ThreadPoolExecutor(1)

    def send(self, type_: str, payload: dict) -> None:
        t_ms = int((self._clock() - self._t0) * 1000)
        self._ex.submit(self.sb.broadcast, self.channel_id, type_, payload, t_ms)

    def stage_hook(self, scan_id: str):
        return lambda stage, status, ms: self.send("stage", {"scan_id": scan_id, "stage": stage, "status": status,
                                                             "ms": ms})

    def close(self) -> None:
        self._ex.shutdown(wait=True)


def new_id() -> str:
    return str(uuid.uuid4())
