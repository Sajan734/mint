# seller: the seller's web app

Selling on Mint is one action: **scan the item**. The pipeline writes the name, description, condition and a
recommended price; the seller reviews it. (The buyer's side is `../buyer/`.)

```
/                     landing, "Scan an item"
/scan/new             starts a session: a new scan id (UUID), redirects to /scan/{id}
/scan/{id}            QR code -> iPhone; then live progress; then on to the draft
/listing/{id}         the draft listing: 3D spin, title, recommended price + why, description, condition
```

## How the computer reaches the phone

The QR code on `/scan/{id}` encodes `mint://scan?id={id}`. Scanning it with the iPhone camera opens the Mint app
straight into a capture for that id. The app records, uploads `scans/{id}/video.mp4` (via the `scan-upload` Edge
Function, no key), and the Supabase webhook starts the pipeline (gsplat/README.md). This page follows along:

- **Realtime** channel `batch:{id}`: the splat job's `stage` events (progress bar). Needs `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- **Public files** (polled every 2 s, the source of truth): `assets/splats/{id}.json` (3D scan done, spin frames),
  then `assets/listings/{id}.json` (listed / rejected / failed).

What the iOS app needs (role C): register the `mint` URL scheme, and on `mint://scan?id=...` start a capture that
uploads under that id instead of a fresh UUID.

## Run

```bash
pnpm install
pnpm dev        # http://localhost:3001 (the buyer site uses 3000)
pnpm check      # typecheck + lint + tests
```

Settings come from the repo-root `.env` (see `../.env.example`): `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (optional, live progress), `NEXT_PUBLIC_MINT_SCAN_LINK` (default `mint://scan`),
`NEXT_PUBLIC_BUYER_URL` (default `http://localhost:3000`).

## Not built yet

Editing the draft and choosing a price inside the band, seller accounts, and a "publish" step (today every listed
scan appears on the buyer site as soon as it is written).
