# buyer: the buyer's web app

Browse second-hand items scanned in 360° and priced fairly; reserve, buy, verify on delivery. (The seller's side
is `../seller/`; the buyer-side comparison agent is `../multiagent/buyer_agent/`.)

Listings are the mock data in `mock/` plus **live scans** from the pipeline: `lib/data/live.ts` reads the public
`assets/listings/index.json` that the splat + listing job publishes (see `../gsplat/README.md`), keeps the
schema-valid listed ones, newest first. If Supabase is unreachable the site shows the mock data only.

```bash
pnpm install
pnpm dev        # http://localhost:3000
pnpm check      # typecheck + lint + unit tests;  pnpm test:e2e for Playwright
```

Settings come from the repo-root `.env` (see `../.env.example`): `NEXT_PUBLIC_SUPABASE_URL` (defaults to the team
project) and `MINT_LIVE_LISTINGS` (`0` hides live scans).
