# Dashboard ↔ scanner hand-off

How the seller's web dashboard starts a scan on the phone and follows it live. The phone side is done (`scanner/ios`); this is what the website needs to do. Everything goes through one keyless Supabase Edge Function, [`supabase/functions/scan-session`](supabase/functions/scan-session/index.ts), so neither the browser nor the phone holds a key.

```
Seller dashboard                         scan-session (Edge Function)            Mint app on the phone
────────────────                         ────────────────────────────            ─────────────────────
click "New product" ── request ────────▶ session {status: waiting} ◀── next ──── "Ready when you are" (polls every 1.5 s)
"Check your phone…"                                                  ──────────▶ scanner opens by itself (buzz)
   poll status every 1–2 s ── status ──▶ scanning (passes: 0, 1, 2…) ◀── update ── laps, Scan again, Done
                                         uploading (progress 0…1)    ◀── update ── sending
                                         uploaded                    ◀── update ── "Look back at your computer"
then wait for the listing ──▶ assets/listings/index.json: scans[] with the same scan_id (A's pipeline: splat → listing)
```

**Endpoint:** `POST https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-session`, JSON body, no auth header, CORS open. (Needs deploying once; see the end.)

## 1. "New product" button

```ts
const SESSION = "https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-session";
const call = (body: object) =>
  fetch(SESSION, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => r.json());

const session = await call({ action: "request", title: "Logitech mouse", seller: "sajan" }); // title/seller optional, ≤ 120 chars
router.push(`/new/${session.scan_id}`);   // the "check your phone" page
```

The phone shows `title` on the scanner ("NEW PRODUCT · LOGITECH MOUSE"), so pass it if the seller typed one.

## 2. The "check your phone" page

Poll `{ action: "status", scan_id }` every 1–2 s. It returns the session:

```json
{ "v": 1, "scan_id": "…", "status": "scanning", "source": "dashboard", "title": "Logitech mouse", "seller": "sajan",
  "passes": 1, "progress": 0, "created_at": "2026-10-17T15:00:00.000Z", "updated_at": "2026-10-17T15:00:21.000Z" }
```

| `status` | What's happening on the phone | Suggested page copy |
|---|---|---|
| `waiting` | Not picked up yet (the app is opening the scanner) | "Check your phone: the Mint scanner is opening." + the QR below |
| `scanning` | Scanner open; `passes` = passes recorded so far | "Scanning on your phone…" (`passes` ≥ 1: "2 passes recorded") |
| `uploading` | Sending the video(s); `progress` 0…1 | "Uploading your scan… 63%" |
| `uploaded` | Phone is done ("look back at your computer") | "Building your 3D scan…", then step 3 |
| `cancelled` | Seller tapped ✕ on the phone | "Scan cancelled." + a button to try again |

A request the phone doesn't pick up within **10 minutes** expires (the phone ignores it). Only the **latest** request is offered to the phone, so clicking New product twice just replaces the first.

**If the app isn't open:** show a QR code of `mintscan://scan?scan_id=<scan_id>` on this page. Pointing the iPhone camera at it opens Mint straight into the scanner for this product (any QR library, e.g. `qrcode` on npm). The phone also picks requests up by itself whenever it's on its home screen ("Ready when you are"), so for the demo, leave the app open there.

## 3. The result

After `uploaded`, the splat pipeline (Role A) runs on `scans/{scan_id}/` and publishes to the public `assets/listings/index.json`, which the site already reads (`multiagent/web/lib/data/live.ts`). Poll it until `scans[]` has an entry with this `scan_id`: `status: "listed"` (show the review page) or `"failed"` (show `error`).

## What the phone uploads

See [HANDOFF.md](HANDOFF.md): `scans/{scan_id}/video.mp4` (+ `bottom.mp4` if the item was flipped for a second pass, + poses and capture info). The website never needs these directly.

## Deploying the function (once)

Supabase dashboard of project `jpanyhsifoxxiizkgjno` → Edge Functions → Deploy a new function → Via editor → name **`scan-session`** → paste [`supabase/functions/scan-session/index.ts`](supabase/functions/scan-session/index.ts) → Deploy → in its settings turn **off** "Enforce JWT verification". Check:

```bash
curl -s -X POST https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-session -H 'Content-Type: application/json' -d '{"action":"next"}'
# → {"request":null}
```

The phone's waiting screen then says "Connected to your dashboard". It's open to anyone with the URL (fine for the hackathon; add auth afterwards).
