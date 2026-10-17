# Role D — Product, money and trust (v3)

**Mission:** turn measured evidence into a fair, traceable price and a sale page anyone can trust, make every record verifiable, and lead the pitch.
**Owns:** M10, M11, M12, M13, M14 (UI), M15, M18 (dataset with B), N1–N3. Next.js product pages, price engine + comps, signed records, Supabase schema, API skeleton, contract regeneration, Devpost, pitch. Code: `backend/api/`, `backend/price/`, `backend/record/`, `web/` (except stage + demo), `web/lib/crypto/`, `supabase/`, `contracts/`, `data/comps/`.
**Sleeps:** H10–H13 (Sat 8–11 AM). Nap H28–H29.5.
**Read first:** [ARCHITECTURE.md §7 price engine](../ARCHITECTURE.md#7-fair-price-engine-d), [§8 records](../ARCHITECTURE.md#8-signed-records-and-keys-d-c-for-the-ios-key), [§9 contracts](../ARCHITECTURE.md#9-contracts-v3), [§10 API](../ARCHITECTURE.md#10-api-fastapi-on-modal----added-to-the-specs-list), [DEMO.md](../DEMO.md).

## Interfaces

| Direction | Contract | With | By |
|---|---|---|---|
| produces | API skeleton (all routes stubbed with schema-valid responses), Supabase migration, `broadcast()` + `stage()` helpers, v3 contracts + generated types | everyone | H1 |
| produces | Comps `data/comps/{model_key}.json` + [constants/price_v3.json](../contracts/constants/price_v3.json) | price engine, web | H4 |
| produces | Crypto: canonical JSON (Python + TS), PyNaCl verify, tweetnacl buyer key; interop with C's CryptoKit | C | H4 |
| consumes | [passport](../contracts/passport.schema.json), `/keyframe` | A | H6 / H13 |
| consumes | [region](../contracts/region.schema.json), [verdict](../contracts/verdict.schema.json), [identity](../contracts/identity.schema.json) | B | H13 |
| produces | [price_band](../contracts/price_band.schema.json), [statement](../contracts/statement.schema.json), [handover_result](../contracts/handover_result.schema.json), [record](../contracts/record.schema.json) + `price`/`statement`/`handover_result`/`record_ready`/`sealed` events | C (stage), web | H16 |
| produces | Eval dataset (with A), labels with B | B | H13–H20 |

## Fixtures

Real comps with source URLs; real regions from B's runs (never hand-made region JSON) for the price engine's integration tests. Unit tests may use small literal inputs because the engine is pure arithmetic, but every test case must be traceable to a real scenario.

## Pre-hack

- [ ] **Hacker package:** judging format/time, prizes, whether pre-hack curation is allowed (D9). Tell the team.
- [ ] **Comps with sources** for the demo objects and the 8 batch items.
- [ ] Accounts (Supabase, Vercel, Modal, Devpost, model keys); sticker sheet + marker; script draft; sourced problem statistics.

## Tasks

| # | Window | Task | Done when |
|---|---|---|---|
| D1 | H0–1 | **Run the contract lock** (walk through `contracts/` and CLAUDE.md §8); generate Pydantic + TS types; Supabase migration (tables per ARCHITECTURE §12, RLS: anon read, writes via service role); FastAPI on Modal with every route stubbed; `broadcast()` + `stage()`; Next.js deployed; canonical JSON in Python + TS reproduces `test-vectors/record_v3.json` | **★ H1** |
| D2 | H1–4 | **Price engine, test-first:** determinism, Σ ledger = market − mid, FLOOR scaling, band width vs uncertain/unconfirmed share, price-neutral classes, chosen price must stay inside the band, handover adjustment. Record builder (integers only) + PyNaCl verify; tweetnacl module; **CryptoKit ↔ PyNaCl ↔ tweetnacl interop test with C** | All three verify each other; engine tests green |
| D3 | H4–10 | Passport viewer `/p/[itemId]` (Spark: drag, tilt, glowing regions, coverage badge, tap-for-photo via `/keyframe`, price breakdown, "How is this priced?"); sale page `/s/[batchId]` skeleton; review queue `/review/[batchId]`; deals: `POST /deals`, `/h/[dealId]` with buyer key + `/join` | A QR opens the passport on a phone |
| — | H10–13 | 💤 | — |
| D4 | H13–16 | Wire B's verdicts → price → ledger lines linked to regions; `/items/{id}/confirm` → re-price, band narrows; `/items/{id}/price` (inside band only); `/batches/{id}/publish`; listing record signed by the seller | **★ H16:** price band, review queue, sale page, signed record end to end |
| D5 | H16–20 | Household statement `/statement/[batchId]` with the 8-item batch (cards + totals); handover result `/h/[dealId]` (red vs amber, wipe, buyer confirms `needs_confirmation`, adjustment, sign); verify page `/v/[recordId]` with in-browser re-verification + tamper mode; label eval regions with B | 5-item review < 1 min; 1-byte edit fails |
| D6 | H20–23 | Devpost: problem (sourced), solution, architecture diagram ([docs/diagrams/v3-overview.png](../docs/diagrams/v3-overview.png)), live vs cached, honest limits, micro-loan extension | **★ H23** |
| D7 | H23–34 | Numbers into DEMO.md and the pitch at H26; rehearsals with injected failures; Q&A drill; final submission | **★ H32**, **★ H34** |
| N1–N3 | after gate 4 | Inbox agent (answers with rendered views, offers validated in code); two-agent settlement (private limits, arbiter in code); measure tool | — |

## Fallbacks

| If | Then |
|---|---|
| B's verdicts late | Price engine runs on RulesV0 verdicts; UI unchanged |
| Comps missing for an item | Fixed comps table with a visible "estimate" label |
| CryptoKit interop fails | C signs in a web view with tweetnacl |
| Two-device signing fails on stage | Spare phone signs as buyer; else hash + single signature, said honestly |
| No sourced statistics | Lead with the live demo and our photo-only baseline number |
