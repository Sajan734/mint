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
| `scans` | private (signed URLs) | `{scan_id}/video.mp4`, `{scan_id}/bottom.mp4` (optional), the app's `poses.jsonl`, `capture.json`, `session.json` (scanner/HANDOFF.md) |
| **`assets`** | public read | `splats/{scan_id}.spz`, `splats/{scan_id}.json` (manifest), `splats/index.json` (all scans, newest first), `heldout/{scan_id}/` (8 masked video frames `00.jpg`…`07.jpg` + `heldout.json`), `spin/{scan_id}/` (spin frames), `listings/…`, `comparisons/…` (gsplat/README.md). Scans made before 2026-10-17 have `views/{scan_id}/` instead |
| `fixtures` | private | raw eval and test captures |

Supabase reserves the name `public`, so ARCHITECTURE.md §12's `public` bucket is **`assets`**.

Everything in `assets` is readable by URL without a key, so consumers that only read published scans need none:
`listing/ingest.py` polls `splats/index.json` and turns each scan into a listing item folder
(`python ingest.py --latest` / `--watch`). The splat job's publishing code is `gsplat/mintsplat/publish.py`.

Recreate on a fresh project with [`buckets.sql`](buckets.sql). Free plan: **50 MB per file**, 1 GB total
storage, 5 GB egress / month; delete raw videos after processing if space gets tight.

**Back up before deleting anything:** `python supabase_setup/backup.py [out_dir]` copies every object of every
bucket into `supabase_clear/` (gitignored), skips files already there, checks every size and writes
`inventory.json`. The 2026-10-17 cleanup's full copy is there (1,229 objects, 853 MB).

## Keys: who holds what

| Key | Where | Can |
|---|---|---|
| secret / `service_role` | the repo-root `.env` (gitignored; `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`), sent to Modal with each deploy | everything; bypasses RLS |
| publishable / `anon` | web app (`NEXT_PUBLIC_SUPABASE_ANON_KEY`, Vercel) | only what policies allow (reads) |
| none | **iOS app** | uploads with signed URLs issued by the backend |

Never put the service key in the app, the web code, git, or a chat. Keys are in the dashboard under
Project Settings → API Keys.

There is no Modal secret to create: `modal deploy` reads both from `.env` (`supabase_setup/env.py`) and sends them
with the app, to whichever workspace `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` in `.env` belong to.

## Use it from a backend

```python
from supabase_setup.storage import ASSETS, SCANS, Events, Supabase

sb = Supabase()                                       # reads SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
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

## Live pipeline: upload signer and webhook

Two one-time dashboard steps connect the phone to the pipeline (see gsplat/README.md for the whole flow).
**Done on 2026-10-17**: `scan-upload` and `scan-session` are deployed (JWT verification off) and the trigger exists.

1. **Edge Functions → Deploy a new function → Via editor**, name `scan-upload`, paste
   `scanner/supabase/functions/scan-upload/index.ts` (C's signer: one-time upload URLs for
   `scans/{uuid}/video.mp4` etc., no key in the app), Deploy, then turn **off** "Enforce JWT verification".
   The app's `MINT_UPLOAD_URL` is `https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-upload`.
2. **SQL Editor**: run what `python gsplat/client.py urls` prints ([`webhook.sql`](webhook.sql) with the deployed
   `on_upload` URL filled in; again after moving to another Modal workspace). Each new `scans/*/video.mp4` then
   POSTs to `on_upload`, which starts the splat and listing steps once per scan (`rescan.mp4`: the buyer's check).

## Expected latency (phone → splat → downstream)

| Step | Expected | Driver |
|---|---|---|
| Phone → `scans/` (2 × ~20 MB) | 5–15 s | phone uplink (upload video 1 while filming video 2 to hide it) |
| Upload done → GPU job starts | ~0.2 s warm | `mint-api` calls `.spawn(scan_id)` |
| Job downloads videos | ~1 s | datacenter ↔ Supabase |
| Splat (H100, top + bottom) | ~29 s | see `gsplat/README.md` |
| Write `.spz` + views + manifest | < 1 s | ~4 MB |
| Realtime event to subscribers | ~0.1 s | broadcast |
