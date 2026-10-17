# buyer: the buyer's web app (and the one front door)

Browse second-hand items scanned in 360° and priced fairly. Reserve an item or contact the seller. When you get the
item, scan it to compare it with the seller's scan. The seller's side is `../seller/`, served under `/sell` on the same origin
(Next.js multi-zones). The buyer-side comparison agent is `../multiagent/buyer_agent/`.

## Run the whole site (one origin)

Two dev servers, one address. The buyer app owns `/` and proxies `/sell/*` to the seller app.

```bash
# terminal 1: the seller zone, on port 3001
cd seller && pnpm install && pnpm dev     # next dev --port 3001

# terminal 2: the buyer zone, on port 3000
cd buyer && pnpm install && pnpm dev      # http://localhost:3000
```

Open **http://localhost:3000**. Everything goes through that address: `/` is the landing page, **Sell an item** goes
to `/sell` (the seller app). Do not open `:3001` directly: seller pages use buyer files (`/frames/...`,
`/local/...`) that only exist on the shared origin. If the seller app runs elsewhere, set `SELLER_ORIGIN` (default
`http://localhost:3001`) before starting the buyer app.

Add `?mock=1` to any URL for demo data. Demo data needs no phone and no backend. A "Demo data" pill then shows in
the header, with **Turn off**. `?mock=0` also turns it off.

## Data

Listings are the mock data in `mock/` plus **live scans** from the pipeline: `lib/data/live.ts` reads the public
`assets/listings/index.json` that the splat + listing job publishes (see `../gsplat/README.md`), keeps the
schema-valid listed ones, newest first. If Supabase is unreachable the site shows the mock data only.

Listings published from `/sell` in this browser live in `localStorage` (`mint.listings.v1`, `lib/local-listings.ts`).
They show under **Just listed** on the landing page, and `/listing/{id}` renders them on this device only.

## Checks

```bash
pnpm check      # typecheck + lint + unit tests
pnpm test:e2e   # Playwright (builds and serves on port 3107)
```

Settings come from the repo-root `.env` (see `../.env.example`): `NEXT_PUBLIC_SUPABASE_URL` (defaults to the team
project), `MINT_LIVE_LISTINGS` (`0` hides live scans) and `SELLER_ORIGIN`.
