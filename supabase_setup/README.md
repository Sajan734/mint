# supabase_setup: shared Supabase layer

Supabase is Mint's shared bus ([ARCHITECTURE.md](../ARCHITECTURE.md) §1): **Storage holds the bytes,
Postgres holds the truth, Realtime pushes to the stage and phones.** This folder has the project setup,
a dependency-free Python client for backends, and a smoke test.

| | |
|---|---|
| Project | `mint` · `https://jpanyhsifoxxiizkgjno.supabase.co` (Free plan, region Americas) |
| Dashboard | https://supabase.com/dashboard/project/jpanyhsifoxxiizkgjno (ask the owner for an invite) |
| Tables | none yet; D's migrations (`supabase/migrations/`) |

## Buckets

| Bucket | Access | Keys |
|---|---|---|
| `scans` | private (signed URLs) | `{scan_id}/top.mp4`, `{scan_id}/bottom.mp4` (any video extension) |
| **`assets`** | public read | `splats/{scan_id}.spz`, `splats/{scan_id}.json` (manifest), `splats/index.json` (all scans, newest first), `views/{scan_id}/` (8 reference views: `NN_azAAA_elEE.png` transparent + `_grey.png`, and `views.json` with cameras), later `thumbs/…`, `refs/…`, `renders/…`, `maps/…`, `wipes/…` |
| `fixtures` | private | raw eval and test captures |

Supabase reserves the name `public`, so ARCHITECTURE.md §12's `public` bucket is **`assets`**.

Everything in `assets` is readable by URL without a key, so consumers that only read published scans need none:
`listing/ingest.py` polls `splats/index.json` and turns each scan into a listing item folder
(`python ingest.py --latest` / `--watch`). The splat job's publishing code is `gsplat/mintsplat/publish.py`.

Recreate on a fresh project with [`buckets.sql`](buckets.sql). Free plan: **50 MB per file**, 1 GB total
storage, 5 GB egress / month; delete raw videos after processing if space gets tight.

## Keys: who holds what

| Key | Where | Can |
|---|---|---|
| secret / `service_role` | **Modal secret `mint-supabase`** only (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`) | everything; bypasses RLS |
| publishable / `anon` | web app (`NEXT_PUBLIC_SUPABASE_ANON_KEY`, Vercel) | only what policies allow (reads) |
| none | **iOS app** | uploads with signed URLs issued by the backend |

Never put the service key in the app, the web code, git, or a chat. Keys are in the dashboard under
Project Settings → API Keys.

Create the Modal secret once (Modal dashboard → Secrets → Custom, or in your own terminal):

```bash
modal secret create mint-supabase SUPABASE_URL=https://jpanyhsifoxxiizkgjno.supabase.co SUPABASE_SERVICE_ROLE_KEY=<secret key>
```

Teammates' Modal apps can only use it if they're in the same Modal workspace.

## Use it from a backend

```python
from supabase_setup.storage import ASSETS, SCANS, Events, Supabase

sb = Supabase()                                       # reads the secret's env vars
video = sb.download(SCANS, f"{scan_id}/top.mp4")
url = sb.upload(ASSETS, f"splats/{scan_id}.spz", data, "application/octet-stream")  # -> public URL
upload_url = sb.signed_upload_url(SCANS, f"{scan_id}/top.mp4")   # hand to the phone; it PUTs the file
ev = Events(sb, batch_id)                             # background, in-order Realtime events
ev.send("passport_ready", passport); ev.close()
```

In a Modal image: put the repo root on `sys.path` in the app file and add
`.add_local_python_source("supabase_setup")` (see [`modal_app.py`](modal_app.py)).

## Realtime

Channel `batch:{batch_id}` (`deal:{deal_id}` for handovers). Every message uses the contract envelope
[`realtime_event.schema.json`](../contracts/realtime_event.schema.json): `{v: 3, type, id, at, t_ms, payload}`,
sent as Broadcast event `type`. `Supabase.broadcast` never raises (live UI must not fail a pipeline).

## Smoke test and the signed-upload function

```bash
modal run supabase_setup/modal_app.py      # buckets reachable, upload/download, signed upload, broadcast, with timings
modal deploy supabase_setup/modal_app.py   # exposes sign_uploads(scan_id, names) as app "mint-supabase"
```

## Expected latency (phone → splat → downstream)

| Step | Expected | Driver |
|---|---|---|
| Phone → `scans/` (2 × ~20 MB) | 5–15 s | phone uplink (upload video 1 while filming video 2 to hide it) |
| Upload done → GPU job starts | ~0.2 s warm | `mint-api` calls `.spawn(scan_id)` |
| Job downloads videos | ~1 s | datacenter ↔ Supabase |
| Splat (H100, top + bottom) | ~29 s | see `gsplat/README.md` |
| Write `.spz` + views + manifest | < 1 s | ~4 MB |
| Realtime event to subscribers | ~0.1 s | broadcast |
