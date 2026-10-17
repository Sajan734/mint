"""Minimal Supabase client (Storage + Realtime broadcast) over plain HTTPS.

Runs only inside Modal: the service-role key comes from the `mint-supabase` secret
(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) and never leaves the backend. Clients (the iOS app,
client.py) only ever see short-lived signed upload URLs.
"""
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

SCANS, ASSETS = "scans", "assets"  # private videos / public outputs (Supabase reserves "public")


class Supabase:
    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self._auth = {"apikey": key, "Authorization": f"Bearer {key}"}

    def _req(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> bytes:
        req = urllib.request.Request(self.url + path, data=body, method=method,
                                     headers={**self._auth, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Supabase {method} {path} -> {e.code}: {e.read()[:300]!r}") from None

    # ---- storage
    def download(self, bucket: str, path: str) -> bytes:
        return self._req("GET", f"/storage/v1/object/authenticated/{bucket}/{path}")

    def list(self, bucket: str, folder: str) -> list[str]:
        """File names directly inside `folder`."""
        body = json.dumps({"prefix": folder.rstrip("/"), "limit": 1000}).encode()
        items = json.loads(self._req("POST", f"/storage/v1/object/list/{bucket}", body,
                                     {"Content-Type": "application/json"}))
        return [i["name"] for i in items if i.get("id")]  # folders have no id

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> str:
        self._req("POST", f"/storage/v1/object/{bucket}/{path}", data,
                  {"Content-Type": content_type, "x-upsert": "true", "Cache-Control": "max-age=3600"})
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
