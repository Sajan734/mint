# Website → scanner: how to open the Mint app

Two places on the website open the scanner on the phone. Both are a **link with a scan id**, shown as a QR code:

| Where | Link | What the phone does | Where the video goes |
|---|---|---|---|
| Seller: **Scan an item** / New product | `mint://scan?id=<new uuid>` | Opens the scanner for a listing scan | `scans/<id>/video.mp4` (+ `bottom.mp4`…): the splat → listing pipeline starts by itself |
| Buyer, listing page: **Scan** (next to Contact seller), at an in-person deal | `mint://verify?id=<new uuid>&listing=<listing's scan id>` | Opens the scanner in **Verify** mode ("matching the listing") | `scans/<id>/rescan.mp4` (+ `rescan.capture.json` with `listing_scan_id`): **not** picked up by the listing pipeline; the handover check compares it with the listing |

- The website makes the id (`crypto.randomUUID()`), shows the QR, and then watches for results under that id. This is what `seller/` on the `seller-web` branch already does for listings (`seller/lib/scan.ts`: `mint://scan?id=…`).
- **Reading the QR:** the iPhone Camera app (tap the banner), or **Mint itself**: its home screen ("Ready when you are") reads QR codes through its own camera, so for a demo just leave Mint open and point it at the screen.
- On a phone, the link can also just be a tapped `<a href="mint://…">`.
- The Android app ([README.md](README.md)) takes the same links: the phone's camera app or Google Lens opens Mint from the QR, and its waiting screen reads QR codes the same way.
- Also accepted: `scan_id=` instead of `id=`, and the older `mintscan://` scheme.
- After the scan the phone says "Look back at your computer" (listing) or "Look back at the listing" (verify).

That's all a website needs. The rest of this file is an **optional** extra: if the `scan-session` function is deployed, the phone (waiting on its home screen) opens the scanner by itself when the seller clicks New product, without a QR, and reports live status (scanning → uploading % → uploaded) the page can show.

## Optional: auto-pickup and live status (`scan-session`)

One keyless Supabase Edge Function, [`supabase/functions/scan-session`](supabase/functions/scan-session/index.ts), so neither the browser nor the phone holds a key.

```
Website                                  scan-session (Edge Function)            Mint app on the phone
───────                                  ────────────────────────────            ─────────────────────
click "New product" ── request ────────▶ session {status: waiting} ◀── next ──── "Ready when you are" (polls every 1.5 s)
"Check your phone…"                                                  ──────────▶ scanner opens by itself (buzz)
   poll status every 1–2 s ── status ──▶ scanning (passes: 0, 1, 2…) ◀── update ── laps, Scan again, Done
                                         uploading (progress 0…1)    ◀── update ── sending
                                         uploaded                    ◀── update ── "Look back at your computer"
then wait for the listing ──▶ assets/listings/index.json: scans[] with the same scan_id (A's pipeline: splat → listing)
```

**Endpoint:** `POST https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-session`, JSON body, no auth header, CORS open. (Needs deploying once; see the end.) For a buyer's verify scan, send `{ "action": "request", "kind": "verify", "listing_scan_id": "<listing's scan id>" }`; the session then carries `kind` and `listing_scan_id`.

### 1. "New product" button

```ts
const SESSION = "https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-session";
const call = (body: object) =>
  fetch(SESSION, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => r.json());

const session = await call({ action: "request", title: "Logitech mouse", seller: "sajan" }); // title/seller optional, ≤ 120 chars
router.push(`/new/${session.scan_id}`);   // the "check your phone" page
```

`title` is kept with the session (the scanner itself shows the tagline "Mint condition, measured." rather than the title), so pass it if the seller typed one.

### 2. The "check your phone" page

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

**Always show the QR too** (`mint://scan?id=<scan_id>`): it works even if the function or the phone's polling doesn't.

### 3. The result

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
