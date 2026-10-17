# CLAUDE.md — Mint (Hack the Valley 11) · v3

> **Read this entire file before you do anything in this repo.** It's the one entry point for every team member and for Claude Code. It holds the full v3 game plan, end to end: what we're building, why, how it works, who owns what, when each thing has to be done, and what to do when something breaks. [ARCHITECTURE.md](ARCHITECTURE.md) has the technical detail and [DEMO.md](DEMO.md) has the pitch runbook.
>
> **Keep it true.** If you change a decision, threshold, formula, route, contract or schedule, update this file **in the same commit**.
>
> **All docs are v3:** [PRD.md](PRD.md), [plans/](plans/), [contracts/](contracts/), [README.md](README.md), [SPEC.md](SPEC.md) (the team's source spec, verbatim). **Where any of them disagrees with this file, this file wins.**

---

## 0. TL;DR

| | |
|---|---|
| **Product** | **Mint**: makes your belongings **verifiable, priceable and liquid** |
| **Theme** | Sustainable FinTech & Economic Inclusion |
| **What it does** | A 20-second **AR-guided** phone scan turns an item into a photoreal **3D Gaussian splat**. One engine, **render-and-compare**, then (1) compares it with the **manufacturer's official reference images** to find wear, damage and missing parts and to check it's the claimed model, (2) turns that evidence into a **fair price band** where every deduction links to a 3D region, (3) does it for a whole household in **garage sale mode** (a household asset statement + one sale page), and (4) at **handover**, compares the buyer's quick rescan against the seller's splat to catch transit damage, producing a **signed, tamper-evident record**. |
| **Why 3D** | A photo can't be re-rendered to match a reference image's angle. A splat can, which makes like-for-like comparison possible. |
| **Team** | **A** = reconstruction · **B** = comparison engine · **C** = iOS capture app + stage view + demo mode · **D** = product web app, money (pricing) and trust (records), Supabase schema, pitch lead |
| **Build window** | **H0 = Fri Oct 16 2026, 10:00 PM ET** → **H34 = Sun Oct 18, 8:00 AM ET** · feature freeze **H20 = Sat 6:00 PM** |
| **Numbers that decide the demo** | Scan → passport **≤ 100 s** · registration + comparison **≤ 15 s per item** · handover check **≤ 20 s** |
| **Golden rules** | Measure first, model second · contracts before code · real scans and real reference images only · Mint **measures and flags, people decide** · a model can never drop a consistently measured finding · every dollar traces to a region or a comp · never pass off cached results as live |

---

## 1. Instructions for Claude Code (and humans), read first

1. **Find out the user's role.** Check `MINT_ROLE` (`A`, `B`, `C` or `D`). If it's unset, ask once: *"Which role are you: A, B, C or D?"* Then read **§11** and **`plans/role-{X}.md`** for that role.
2. **Find out where we are in time.** Run `TZ=America/Toronto date` and compute **H = hours since Fri Oct 16 2026, 22:00 ET**. Compare with §9 (schedule) and §10 (checkpoints). If the user is behind a gate, say so plainly and name the fallback (§17).
3. **No project code before H0.** Before Fri Oct 16, 10:00 PM ET, only these are allowed: docs, planning, accounts, Xcode/device setup, throwaway environment tests **outside this repo**, curating reference images and comps with sources, brand drafts. If you're asked to write project code before H0, say so and offer to plan it instead.
4. **Stay in your lane.** Edit only the directories your role owns (§12). If something in another role's area needs to change, draft the change, tell the user who owns it, and don't commit it yourself.
5. **Contracts are law.** Never change contracts silently (§7.3). Never hand-edit generated types (Python, TypeScript, Swift).
6. **Real data only.** Never invent scans, reference images, comps, region data or synthetic test inputs. Test against captured fixtures and curated references with sources (§13). If none exist yet, say so.
7. **Deterministic first.** If geometry, maths or plain code can answer it, don't use a model. Models are allowed for exactly: (a) recognising the item from a photo, (b) class, severity and present-before **probabilities** for a region, from its **features**, never pixels, and (c) stretch only, the N1 inbox agent and N2 negotiation agents, whose outputs code validates.
8. **Never break the invariants** in §6.6.
9. **Protect the latency budgets.** Every pipeline step emits `stage` timing events. Don't add a stage without fitting it into the budget.
10. **Test-first for pure logic:** the price engine, decision rules, hard floor, canonical JSON, signature verification and pose conversions get table-driven unit tests before the implementation. GPU steps are tested against real fixtures with numeric pass conditions (IoU, reprojection error, region counts, timings).
11. **When unsure, keep the demo working.** Pick the fallback that keeps the end-to-end flow demoable, and ask before making any team-level decision.
12. **Keep docs true.** Update this file (and ARCHITECTURE.md or DEMO.md) in the same commit as any change they describe.

---

## 2. The problem

**Condition is the unpriced variable in second-hand money.** A product's model and age are easy to look up. Its condition isn't, so every second-hand transaction gets discounted for uncertainty, and the people with the least leverage lose the most:

- **Pawnshops and resale stores** pay a fraction of value because they can't trust condition.
- **Lowballers** exploit sellers who don't know what their item is worth.
- **Buyers who rely on second-hand** get burned by hidden damage, misdescribed items and fakes.
- **Households sit on unused belongings** worth hundreds of dollars because pricing and listing each item is too much work.

**Photos don't fix this.** They're cropped, taken at flattering angles, lit differently each time, and never match a reference image or an earlier photo, so condition can't be measured from them.

**Evidence status:** these are **assumptions** until D finds sourced statistics (before H23). No statistic goes into the pitch without a URL. Our photo-only baseline (§13) is first-hand evidence that photos can't be compared reliably.

---

## 3. The product

### 3.1 Four uses of one engine

| # | Use | What happens |
|---|---|---|
| 1 | **Listing** | The splat is compared against the manufacturer's official reference images to find wear, damage and missing parts, and to check the item matches its claimed model (identity check). |
| 2 | **Fair price band** | Market value from comparable sales × a condition multiplier from the measured evidence, with every deduction linked to a highlighted 3D region. |
| 3 | **Garage sale mode** | Scan many items in one session → a **household asset statement** (each item's condition, fair price band, and the total) → publish them all on one sale page. |
| 4 | **Handover** | At delivery, the buyer's quick rescan is compared against the seller's splat to detect transit damage, producing a signed, tamper-evident record. |

### 3.2 End-to-end user journey (what the demo shows)

| # | Who | What happens | Features |
|---|---|---|---|
| 1 | Seller | Opens the **Mint iOS app** and starts a batch (one item = a batch of 1). | M12 |
| 2 | Seller | **Taps the item.** An AR dome anchors to it. They walk around at two heights for 20–25 s while the segments fill. Exposure, focus and white balance are locked. | M1 |
| 3 | System | Within **5 s** the **brand + model + variant pop up** on the phone and the big screen. | M2 |
| 4 | System | At ~90% coverage the upload finishes automatically. Masking (hands dropped), ARKit poses refined by VGGT, gsplat training → **passport in ≤ 100 s** with a **coverage-verified badge**. The phone **seals** the scan hash. | M3, M4, M15 |
| 5 | System | 3–5 **official reference images** are registered to the splat; each **snaps into alignment** on the stage. Anomaly heatmap; lighting noise fades; **real wear glows**. **Identity check** passes or warns. ≤ 15 s. | M5–M8, M16 |
| 6 | System | Each region gets a **typed verdict**. Code routes it: accepted, needs confirmation, uncertain, or dropped. | M9 |
| 7 | System | **Fair price band** builds line by line: comps → market value → one deduction per region → band. | M10 |
| 8 | Seller | **Review queue** (phone web): swipe through items, confirm or dismiss flagged regions (the band narrows), accept or edit the price within the band. | M11 |
| 9 | Seller | Repeats for more items → **household statement** (cards stack into a total) → **publish the sale page**. | M12 |
| 10 | Buyer | Opens the sale page QR on their phone, inspects any item: orbit, tilt, glowing regions, **tap for the real photo**, price breakdown, coverage badge. No app needed. | M13 |
| 11 | Both | Seller creates a **deal**; the buyer opens the deal link, and their browser generates a **buyer key**. | M14, M15 |
| 12 | Buyer | Item changes in transit (demo: the judge adds a sticker and a marker line). A **10 s rescan** (the team's iPhone acts for the buyer). | M14 |
| 13 | System | The rescan is localized into the seller's splat. **New regions glow red next to amber disclosed ones.** Wipe slider at the exact angle. Suggested adjustment. ≤ 20 s. | M14 |
| 14 | Both | The buyer confirms any uncertain regions and **signs on their phone**; the seller signs in the app. **Stamp**, QR, verify page; editing one byte fails verification. | M15 |

### 3.3 Theme fit

| Theme phrase | Mint |
|---|---|
| Expand financial access | Turns unused belongings into fairly priced cash |
| Empower underserved communities | Removes the information gap that lets pawnshops and lowballers underpay |
| Equitable economic growth | Both sides of every deal see the same objective price evidence |
| Financial literacy | A transparent price breakdown tied to measured evidence |

**Pitch extension (not built):** a verified condition record lets possessions serve as collateral for fair micro-loans instead of predatory pawn rates.

### 3.4 Honest positioning (say exactly this in Q&A)

- Mint **measures and flags**; **people make the final call**. Sellers confirm flagged regions before publishing, and buyers can inspect any angle themselves.
- A **coverage-verified** scan means the seller can't hide the bad side, which no photo listing can guarantee.
- The identity check is a **mismatch warning, not counterfeit certification**.
- Signed records prove integrity **after capture**, not that the capture itself was authentic (App Attest and C2PA are extensions).
- Doesn't work well on shiny, glass, transparent or heavily customized items.

---

## 4. Goals and success metrics

**Hypothesis:** objective, reference-based condition measurement + a traceable price band makes second-hand items fairly priceable for the people with the least leverage. For the hackathon, we know we're right when:

1. A live AR scan becomes a passport, and the manufacturer images **visibly snap onto the 3D model** with IoU ≥ 0.85.
2. Known wear is found with **≤ 2 false regions per clean object**, beating a **photo-only baseline**.
3. Every dollar of the price band traces to a region or a comp, and the **same inputs always give the same band**.
4. A judge **inspects items on their own phone**, watches **transit damage appear red beside amber**, and **signs on their own phone**.

| Metric | Target | Measured by | Owner |
|---|---|---|---|
| Scan → passport | ≤ 100 s, 3 of 3 demo objects, venue Wi-Fi | `stage` timing events | A |
| Live recognition | Model shown ≤ 5 s after scan start, 3 of 3 | Timestamps | A |
| AR coverage | 90% in 20–25 s, 3 of 3 | App telemetry | C |
| Registration | Silhouette IoU ≥ 0.85 on ≥ 3 references per demo object; report mean IoU + pose success rate | Comparator logs, eval | B |
| Registration + comparison | ≤ 15 s per item, 3 of 3 (H29) | Timing | B |
| Condition detection | Known wear detected; ≤ 2 false regions per clean object; report precision and recall vs references | Eval set | B |
| Identity check | Correct model passes; wrong reference set warns | Eval | B |
| Handover | Sticker + marker detected; no-change rescan ≤ 2 regions; ≤ 20 s; report precision and recall | Eval set | B |
| Mint vs photo-only baseline | Fewer false regions (report both numbers) | Eval set | B |
| Jev vs simple classifier | Report accuracy and ECE honestly | Eval set | B |
| Decisions | Typed verdict for every region in < 5 s per item | Timing | B |
| Price determinism | Same inputs → same band (unit test); every dollar traced | Tests | D |
| Review speed | 5-item batch reviewed in < 1 min | Stopwatch | D |
| Record integrity | 1-byte edit fails; signatures from 2 devices (iPhone + judge's browser) | Verify page | D |
| Demo | 3 clean timed rehearsals by H32 | DEMO.md log | D |

---

## 5. Every feature

### 5.1 Must-haves

| ID | Feature | Owner | What it is | Done when |
|---|---|---|---|---|
| **M1** | AR-guided capture | C | Tap the item → AR dome anchors → segments fill as the user walks around at two heights. Each sharp frame is saved with its ARKit pose + intrinsics. Exposure, focus and WB lock at start. Upload completes automatically at ~90% coverage. | 20–25 s scan reaches 90% on 3 of 3 demo objects; frames + poses in storage |
| **M2** | Live recognition | A (C for live UI) | First sharp frame uploads immediately. **One** VLM call → label, brand, model, colour variant, category, bbox. Shown on phone and stage during the scan. | Model shown ≤ 5 s after scan start, 3 of 3 |
| **M3** | Object isolation | A | SAM 2 video masking seeded by the box; frames with a hand on the object dropped | Splat contains only the item |
| **M4** | Splat | A | ARKit poses refined with VGGT; gsplat on a warm Modal GPU; compressed web export; keyframe index for tap-for-photo; metric scale from ARKit | Scan → viewable passport ≤ 100 s |
| **M5** | Reference retrieval | A | 3–5 official reference images per item (curated for demo objects; image search best effort) | References present for 3 of 3 demo objects |
| **M6** | Reference registration | B | Each reference's camera pose is solved against the splat: coarse (viewpoint sphere) → fine (LightGlue + PnP with focal sweep) → render-and-optimize on silhouette + features | Silhouette IoU ≥ 0.85 on ≥ 3 references per demo object |
| **M7** | Condition vs references | B | Render at each registered pose, colour-normalise, DINOv2 + high-passed Lab anomalies that **persist across ≥ 2 references**, lift to 3D, cluster into regions with features | Known wear detected; clean surfaces ≤ 2 false regions per object |
| **M8** | Identity check | B | Silhouette + geometry agreement → match score; mismatch warning below threshold | Correct model passes; a wrong reference set warns |
| **M9** | Decisions | B | Jev classifies each region (class, severity, confidence); code rules apply thresholds and route uncertain regions to seller confirmation | Typed verdict for every region in < 5 s per item |
| **M10** | Fair price band | D | Comps (curated) → market value × condition multiplier from confirmed regions; band widens with uncertainty; each deduction links to a region | Same inputs → same band; every dollar traces to a region or a comp |
| **M11** | Seller review queue | D | Swipe drafted listings; confirm or dismiss flagged regions; accept or edit price within the band | 5-item batch reviewed in < 1 min |
| **M12** | Garage sale mode + household statement | D | Batch with per-item condition, band and total; publish as one sale page | Statement + sale page render for a pre-baked 8-item batch |
| **M13** | Passport viewer | D | Splat orbit on phone (drag, tilt), glowing regions, coverage-verified badge, tap-for-real-photo, price breakdown; opens from QR, no app | Judge opens a QR and inspects an item on their own phone |
| **M14** | Handover check | B (engine), D (UI) | Buyer rescan localized into the seller splat (matching inside the mask + PnP), render and compare; new regions red next to disclosed amber | Sticker + marker detected; no-change rescan ≤ 2 regions; ≤ 20 s |
| **M15** | Signed records | D (C for the iOS key) | Canonical JSON, SHA-256, Ed25519: seller key on the capture phone (CryptoKit), buyer key in the browser (tweetnacl); verify page | 1-byte edit fails; signatures from two devices |
| **M16** | Pipeline stage view | C | Big screen: dome filling, registration snapping into place, anomaly heatmap, noise fading, price band building line by line, statement stacking, handover red/amber, seal | Plays for live and cached runs |
| **M17** | Demo mode | C, A | Golden cache for every step, subtle "Replay" indicator | Full demo runs with Wi-Fi off |
| **M18** | Evaluation | B, D | Labelled set; precision and recall; registration accuracy; photo-only baseline; Jev vs simple classifier | Numbers ready by H26 |

### 5.2 Nice-to-haves (only after gate 4; one per person at a time)

| ID | Feature | Owner |
|---|---|---|
| N1 | **Inbox agent:** answers buyer questions with the exact rendered view ("is the bottom scratched?") and accepts or counters offers within seller rules (validated in code) | D |
| N2 | **Two-agent settlement** for handover damage: seller and buyer agents with private limits, arbiter in code (replaces the deterministic adjustment) | D |
| N3 | **Measure tool** on the passport (ARKit metric scale) | D |
| N4 | **Underside flip pass** merged into the splat | A, C |
| N5 | **Calibration chart** (reliability diagram) for the pitch | B |

### 5.3 Cut (do not build, even if asked)

Real payments or escrow · real marketplace posting (no APIs; terms of service) · turntables, marker boards or any extra hardware · on-device splat training · blockchain · shiny, glass or transparent demo objects.

---

## 6. How it works (summary)

**Full detail, diagrams and contracts: [ARCHITECTURE.md](ARCHITECTURE.md).** This section is what every role must know.

### 6.1 Components

iOS app (C) → Supabase Storage + `mint-api` (FastAPI on Modal CPU) → two warm Modal GPU classes: **`Reconstructor`** (A: recognition, SAM 2 + hand filter, ARKit → VGGT poses, gsplat, export) and **`Comparator`** (B: rendering, registration, anomaly maps, lifting and clustering, identity, handover localization + diff). The decision harness (B), price engine (D) and record builder (D) run inside the API. Supabase (Postgres + Storage + Realtime) is the bus. The Next.js app on Vercel serves D's product pages and C's stage view.

### 6.2 Conventions (locked at H1; [ARCHITECTURE.md §2](ARCHITECTURE.md#2-conventions-locked-at-h1))

- **Scan frame** = the listing scan's ARKit world frame, **re-centred on the tap anchor**, **+Y up**, metres. Every 3D quantity for an item lives in it. Handover frames are localized into it.
- **Manifest poses are raw ARKit** (camera-to-world, ARKit camera axes). **A converts once** to OpenCV camera-to-world: `T_cv = translate(−anchor) · T_arkit · diag(1,−1,−1,1)`. Everything downstream uses OpenCV poses.
- **Intrinsics in pixels of the saved JPEG.** Frames are saved in **sensor (landscape) orientation** and K is scaled with the downscale (D2).
- **Viewer** (three.js/Spark) is +Y up, so no world transform is needed. To render from an OpenCV pose: `T_three = T_cv · diag(1,−1,−1,1)`.
- **Reference images** have unknown focal length; B solves it.
- **Signed records: integers only** (cents, basis points). API/UI use normal numbers.
- Every contract carries `"v": 3`. Every listing belongs to a batch.

### 6.3 The three pipelines

| Pipeline | Steps | Budget |
|---|---|---|
| **1. Scan → passport** | Capture (AR dome, pose-tagged frames) → live recognition (one VLM call) → SAM 2 + hand filter → ARKit init + VGGT refine (keep ARKit's metric scale) → gsplat → `.spz` + `.ply` + keyframe index → hash + seller seal → auto-trigger Pipeline 2 | **≤ 100 s** |
| **2. Condition vs references** | Load 3–5 curated references + masks → **coarse pose** (pre-rendered viewpoint sphere; DINOv2 global + silhouette) → **fine pose** (ALIKED/SuperPoint + LightGlue, lift with splat depth, **PnP-RANSAC with focal sweep**) → **render-and-optimize** (pose + focal on silhouette IoU + features) → keep refs with **IoU ≥ 0.85** → render at pose, **histogram-match inside the mask** → **DINOv2 patch distance + high-passed Lab difference** (+ silhouette = missing part) → keep anomalies **persisting in ≥ 2 references** → lift with splat depth → **HDBSCAN** regions → identity score → decisions → price | **≤ 15 s per item** |
| **3. Handover** | Buyer key joins the deal → 10 s rescan (~25 frames) → localize each frame into the seller splat (LightGlue inside the mask + PnP vs splat depth) → render seller splat at each pose → exposure-normalise, DINOv2 + Lab diff → lift + vote + HDBSCAN → decisions with `present_before` (overlap with disclosed listing regions) → **red new / amber disclosed** → deterministic adjustment → record signed by both | **≤ 20 s** |

### 6.4 Decisions (B), rules in code

- Classes: `wear`, `damage`, `missing_part`, `dirt_or_smudge`, `removable_addition`, `scan_artifact`. Plus severity 0–1, and at handover `present_before_prob`.
- Engine: **Jev (TypeSafe)** on region **features**. Fallback: calibrated LogReg + GBR (also the baseline). RulesV0 heuristics until those exist.
- **≥ 0.85 → `accepted`** · **0.5–0.85 → `needs_confirmation`** (seller at listing, buyer at handover) · **< 0.5 → `uncertain`**, excluded from price but widens the band · confident `scan_artifact` → `dropped`.
- **Hard floor:** a region measured consistently in **≥ 70% of the views that see it** can't be dropped as an artifact by any model.
- `removable_addition` and `dirt_or_smudge` **never reduce price**; they appear as notes.
- All thresholds tuned on the eval set, and the pitch says so.

### 6.5 Fair price engine (D), deterministic ([ARCHITECTURE.md §7](ARCHITECTURE.md#7-fair-price-engine-d))

```
market_value    = median(curated comps for model + variant)                (sources cited)
penalty(r)      = W[class] × severity × clamp(sqrt(area_cm2/4), 0.25, 1.5)  over accepted + confirmed regions
condition       = max(0.30, 1 − Σ penalty)
price_mid       = market_value × condition                                 (multiplier = identity in v1)
band_width_frac = 0.08 + 0.30 × (uncertain + unconfirmed) / non-dropped regions
price_band      = price_mid × [1 − w/2, 1 + w/2]
ledger line(r)  = −market_value × penalty(r)   → Σ ledger = market − mid, so every dollar traces to a region
W: wear 0.25 · damage 0.8 · missing_part 1.0 · dirt / removable / artifact 0      (constants in contracts/constants/price_v3.json)
handover adjustment = price_mid(listing ∪ new damage) − price_mid(listing)
```

### 6.6 Invariants (never break these)

1. **Hard floor:** no model output drops a region measured in ≥ 70% of the views that see it. A unit test guards this.
2. **Persistence:** a listing anomaly seen in only one reference never becomes a region.
3. **Price-neutral classes:** `removable_addition` and `dirt_or_smudge` never reduce price.
4. **Traceability:** every ledger dollar links to a region; every market value cites its comps; the price engine is deterministic.
5. **People decide:** `needs_confirmation` regions don't count toward price until a person confirms them; the seller can only set a price inside the band.
6. **Signed records hold integers and strings only**, canonicalized exactly as in [ARCHITECTURE.md §8](ARCHITECTURE.md#8-signed-records-and-keys-d-c-for-the-ios-key).
7. **No secrets in the iOS app or the web app.** The Supabase service-role key lives only on Modal. The iOS app talks only to `mint-api` and to signed upload URLs.
8. **Public images are item-masked;** reference images are stored with their source URL.
9. **The "Replay" pill is always visible on cached steps.** Cached results are never presented as live.
10. **Every pipeline stage emits timing events.**

---

## 7. Contracts

### 7.1 Status

The v3 contract shapes are defined in **[ARCHITECTURE.md §9](ARCHITECTURE.md#9-contracts-v3)**: capture manifest, recognition, passport, registration (+ progress event), region, verdict, identity, price band, statement, handover result, signed record, realtime envelope. The JSON Schemas in [contracts/](contracts/) are **v3 drafts** (16 schemas + `constants/price_v3.json` + `test-vectors/record_v3.json`, sha256 `68b71c27…acab2`), checked during planning: every schema compiles, the vector validates, Python and JS hashes match, and floats in a record are rejected. **D locks them at H1** after the team walk-through.

### 7.2 Generated types (H1)

- Python (Pydantic v2): `datamodel-codegen` → `backend/contracts/models.py`
- TypeScript: `json-schema-to-typescript` → `web/lib/contracts.ts`
- Swift: hand-written `Codable` structs in `ios/Mint/Contracts/` (manifest, recognition, scan responses only), checked against a JSON fixture in a unit test
- Commit generated files; never hand-edit the Python or TypeScript ones.

### 7.3 Changing a contract after H1

1. Post in the team channel: schema, field, why, affected consumers.
2. Get a one-line ack from **every** consumer role.
3. Bump `v` if breaking; edit the schema, regenerate types, update ARCHITECTURE.md §9, all in **one** `contracts:` commit.
4. Consumers fix within the hour.

---

## 8. Decisions log

Defaults we build with. **PROPOSED** items are confirmed at the H1 contract lock. If one changes, edit this table in the same commit.

| # | Question | Default | Status |
|---|---|---|---|
| D1 | Capture platform | **Native Swift + ARKit app** (spec). Fallbacks decided by H6: Apple Object Capture on a LiDAR iPhone, or hand-held video + VGGT | DECIDED |
| D2 | Frame orientation and intrinsics | Save frames in **sensor (landscape) orientation**; scale K with the downscale | PROPOSED |
| D3 | Pose conventions | Raw ARKit in the manifest; A converts once to OpenCV; scan frame = ARKit world re-centred on the anchor, +Y up | PROPOSED |
| D4 | Floats in signed records | **Integers only** (cents, basis points) | PROPOSED |
| D5 | Handover "adjustment" formula | Deterministic re-price delta; agents only as N2 | PROPOSED |
| D6 | Sleep shifts (spec: "two shifts") | Staggered so at most two people sleep at once (§9) | PROPOSED |
| D7 | Jev access unknown | `DecisionEngine` with RulesV0 → FallbackClassifier → Jev | PROPOSED |
| D8 | Reference focal length unknown | Focal sweep in PnP + focal optimized in render-and-optimize | PROPOSED |
| D9 | Is pre-hack curation allowed (references, comps)? | The spec's pre-hack checklist includes it; **D confirms with the hacker package** | OPEN |
| D10 | Who confirms uncertain handover regions? | The buyer, on their phone, before signing | PROPOSED |
| D11 | Price constants | v1 values in §6.5, tuned on the demo objects | PROPOSED |
| D12 | GPU type | A100 vs L4, from A's pre-hack timing run | OPEN |
| D13 | Recognition VLM | Benchmark (e.g. Gemini Flash vs Claude Haiku 5.5) on demo objects: latency + reads model/variant | OPEN |
| D14 | Stage view ownership | `/stage` route + demo player are **C's**, inside D's Next.js app | PROPOSED |
| D15 | Single listing vs batch | Every listing belongs to a batch (single = batch of 1) | PROPOSED |
| D16 | API skeleton owner | **D** (owns the Supabase schema); route owners add their routes | PROPOSED |
| D17 | Demo speakers | As in [DEMO.md](DEMO.md) (D leads; B on the engine beats; C runs capture) | PROPOSED |

---

## 9. Master schedule (hour by hour)

H0 = **Fri Oct 16, 10:00 PM ET**. 💤 = asleep. ★ = checkpoint.

| H | ET | A (reconstruction) | B (comparison engine) | C (iOS + stage) | D (product, money, trust) |
|---|---|---|---|---|---|
| pre | until Fri 10 PM | GPU timing L4 vs A100; VLM benchmark; pick 3–5 matte, textured, **asymmetric** demo objects that have official images; curate **3–5 references each** with sources | Confirm **Jev** access + latency; read gsplat differentiable rendering and LightGlue docs | Mac + Xcode + iPhone ready; **who has a LiDAR iPhone?**; device signing works; brand draft | Hacker package (rules, judging, prizes); curate **comps with sources** for demo objects + 8 batch items; accounts; script draft |
| 0–1 | Fri 10–11 PM | Modal app, image, volumes, `Reconstructor` stub; refs committed under `data/refs/` | `Comparator` stub; `DecisionEngine` interface | **Xcode project runs on device**; ARSession + tap-to-anchor | **Runs the contract lock**; v3 schemas + types; Supabase schema; API stubs; Next.js deployed; canonical JSON vector |
| ★ H1 | Fri 11 PM | All: contracts locked · Modal image builds · Next.js + Supabase deployed · Xcode project runs on device | | | |
| 1–3 | 11 PM–1 AM | **De-risk:** splat of demo object 1 from a hand-held video (VGGT poses); recognition endpoint; reference masks | **Lighting test first:** photo-only baseline vs references + anomaly primitives (histogram match, DINOv2, high-pass) on real phone photos | AR dome, segment logic, sharp-frame selection, pose + K saving | Price engine **test-first**; comps JSON; record builder; sign/verify (Python + tweetnacl) |
| 3–4 | 1–2 AM | Hand the hand-held splat to B; manifest ingest (ARKit → OpenCV) | 💤 3–6.5 | Upload pipeline (signed URLs, first-frame trigger, auto-complete at 90%) | **CryptoKit ↔ PyNaCl ↔ tweetnacl interop test with C** |
| ★ H4 | Sat 2 AM | | | **C:** AR dome anchored and filling; frames + poses upload | |
| 4–6 | 2–4 AM | Real AR manifests → SAM 2 + hand filter → ARKit + VGGT → gsplat → passport | 💤 | Live recognition display, exposure/focus/WB lock; 💤 from 4.5 | Passport viewer (Spark) on phone, sale page skeleton |
| ★ H6 | Sat 4 AM | **A:** real AR scan → splat viewable in browser | | | |
| 6–8 | 4–6 AM | 💤 6.5–10 | Renderer at keyframe poses + self-check; coarse viewpoint sphere | 💤 until H8 | Review queue UI, price panel, deals + join, browser crypto |
| 8–10 | 6–8 AM | 💤 | Fine pose + focal sweep + render-and-optimize → IoU | Stage view skeleton: dome mirror, splat reveal, **registration snap** | Finish UI wiring; hand off to C and B; 💤 from H10 |
| ★ H10 | Sat 8 AM | | **B:** splat rendered at a reference pose with IoU ≥ 0.85 on one object | | |
| 10–13 | 8–11 AM | Keyframe index + tap-for-photo; tune to 100 s; golden splats of the demo objects | Anomaly maps, persistence, lift + cluster on 3 objects; **handover localization + diff on one pair** | Stage: heatmap, noise fade, ledger build; demo recorder; handover mode in app | 💤 10–13 |
| ★ H13 | Sat 11 AM | | **B:** anomaly regions vs references on 3 objects; handover diff on one pair | | |
| 13–16 | 11 AM–2 PM | Hash + seal hook; quality warnings; eval scans with D; start scanning the **8-item batch** | Identity check; decision harness (RulesV0 → classifier); Jev | Seller signing in app (CryptoKit); `capture_progress` events; stage statement + handover visuals | Price band ↔ regions, review confirm flow, sale page, **signed record end to end** |
| ★ H16 | Sat 2 PM | | | | **D:** price band, review queue, sale page and signed record end to end |
| 16–20 | 2–6 PM | Golden assets: 3 demo objects, 8-item batch, golden handover (all real runs, recorder on); N4 only after gate 4 | Latency: registration ≤ 15 s, handover ≤ 20 s; eval labelling | **Demo mode offline**; full demo on a new object; **backup video at H20** | Household statement, handover result UI, verify page + tamper test |
| ★ H20 | Sat 6 PM | **FEATURE FREEZE.** C: full demo on a new object with stage visualizations; demo mode offline | | | |
| 20–23 | 6–9 PM | Fixes; timed runs logged | Evaluation runs (metrics + baselines) | Stage polish, projector readability | **Devpost draft → submit** |
| ★ H23 | Sat 9 PM | | | | **D:** initial Devpost |
| 23–26 | 9 PM–12 AM | Fixes; 💤 nap 25–26.5 | 💤 nap 23.5–25; numbers table | Polish; reduced motion | Numbers into DEMO.md + pitch; rehearsal 1 |
| ★ H26 | Sun 12 AM | | **B:** evaluation numbers and baselines | | |
| 26–29 | 12–3 AM | Warm containers from H28 | Live runs 3 of 3; N5 chart | 💤 nap 26.5–28 | Rehearsal 2, Q&A drill; 💤 nap 28–29.5 |
| ★ H29 | Sun 3 AM | | **B:** live registration ≤ 15 s and handover ≤ 20 s, 3 of 3 | | |
| 29–32 | 3–6 AM | Rehearse | Rehearse | Rehearse | Rehearsal 3 with an injected failure each time |
| ★ H32 | Sun 6 AM | | | | **D:** 3 clean timed rehearsals |
| 32–34 | 6–8 AM | Standby | Standby | Release tag `v1.0-demo` by H33, final deploy | **★ H34 final submission** |

**Sleep plan (D6):** B H3–H6.5 (1–4:30 AM, while waiting for the first real splat) · C H4.5–H8 (2:30–6 AM, after the H4 gate) · A H6.5–H10 (4:30–8 AM, after the H6 gate) · D H10–H13 (8–11 AM). At most two people asleep at once. Saturday-night naps: B H23.5–25, A H25–26.5, C H26.5–28, D H28–29.5. **Before sleeping, post a hand-off note:** what works, what's broken, what the next person needs.

---

## 10. Checkpoints and gates

### 10.1 Checkpoints (the caller posts PASS or FAIL in the team channel on time)

| ★ | ET | Caller | Pass | If it fails |
|---|---|---|---|---|
| H1 | Fri 11 PM | All | Contracts locked; Modal image builds; Next.js + Supabase deployed; **Xcode project runs on device** | D makes the final call on open contract questions; whoever's blocked gets help now |
| H4 | Sat 2 AM | C | AR dome anchored and filling; frames + poses upload | C keeps going; A builds splats from hand-held video meanwhile; **by H6 decide the fallback** (Object Capture on LiDAR, or hand-held video + VGGT) |
| H6 | Sat 4 AM | A | Real AR scan → splat viewable in browser | ARKit poses only (skip VGGT); fewer frames and iterations; hand-held video path |
| H10 | Sat 8 AM | B | Splat rendered at a reference pose with IoU ≥ 0.85 on one object | Coarse pose only, best reference kept; try more references or a different demo object |
| H13 | Sat 11 AM | B | Anomaly regions vs references on 3 objects; handover diff on one pair | Lab difference only (drop DINOv2); fewer references; handover localization fallback: slower rescan |
| H16 | Sat 2 PM | D | Price band, review queue, sale page and signed record end to end | Fixed comps table; hash + single signature; simplify the review queue |
| H20 | Sat 6 PM | C | Full demo on a new object with stage visualizations; demo mode offline. **Feature freeze** | Freeze anyway; cut unfinished features; demo mode before everything else |
| H23 | Sat 9 PM | D | Initial Devpost | Submit whatever exists; edit later |
| H26 | Sun 12 AM | B | Evaluation numbers and baselines | Report what exists with the true n; never extrapolate |
| H29 | Sun 3 AM | B | Live registration ≤ 15 s and handover ≤ 20 s, 3 of 3 | Keep live if ≤ 30 s with filler talk; otherwise the golden result with a spoken handoff |
| H32 | Sun 6 AM | D | 3 clean timed rehearsals | Cut the riskiest live beat; rehearse again |
| H34 | Sun 8 AM | D | Final submission | — |

**Red-flag rule:** if you're **one hour** behind a gate you feed, say so in the channel immediately and switch to your fallback.

### 10.2 Build gates (each ends demoable)

1. **Scan → passport** (H4 → H6)
2. **Registration + condition vs references** (H10 → H13)
3. **Price band + review queue + sale page** (H16)
4. **Handover + signed record** (H13 engine, H16 record)
5. **Stage visualizations, brand, demo mode** (H20 → H32)
6. **Stretch** N1–N5, only after gate 4

---

## 11. Roles in detail

Summary per role; the full plans with interfaces, fixtures and fallbacks are in [plans/](plans/).

### Role A: reconstruction
**Owns:** Modal GPU image + warm containers; recognition VLM; SAM 2 masking + hand-frame filter; ARKit pose ingestion + VGGT refinement; gsplat training + export; keyframe index + `/keyframe`; **reference image curation** (`data/refs/`); golden scans. Code: `backend/recon/`, `data/refs/`.

| # | Window | Task | Done when |
|---|---|---|---|
| A0 | pre | GPU timing (L4 vs A100); VLM benchmark; demo objects chosen (matte, textured, asymmetric); 3–5 references each with sources | D12, D13 decided; refs saved with `refs.json` |
| A1 | H0–1 | Modal app, image, volumes (`mint-weights`, `mint-work`), `Reconstructor` with `@modal.enter` loading SAM 2, VGGT, gsplat | Warm call < 20 s; H1 passes |
| A2 | H1–3 | De-risk splat from a hand-held video (VGGT-only poses); recognition endpoint (strict JSON); reference product masks | A splat of object 1 loads in Spark; recognition 3 of 3 |
| A3 | H3–4 | Hand that splat to B; manifest ingest: ARKit → OpenCV, re-centre on the anchor, K check | Unit test on pose conversion passes on a real manifest |
| A4 | H4–6 | Real AR scan: SAM 2 + hand filter → ARKit init + VGGT refine (Sim(3), keep metric) → gsplat → `.spz` + `.ply` + keyframes | **★ H6** |
| A5 | H10–13 | Keyframe index + `/keyframe` (occlusion-checked, sharpness × view angle × centrality); tune to **≤ 100 s**; golden splats of demo objects | Tap 10 random points per object → right photo |
| A6 | H13–16 | `scan_sha256` + seal hook; quality warnings (low coverage, few sharp frames); eval scans with D; start the 8-item batch | Hash stored; warnings show |
| A7 | H16–20 | Golden assets with the recorder: 3 demo objects, **8-item batch**, golden handover; keep-alive | Replays offline in C's player |
| A8 | H20–34 | Fixes, timed runs, warm containers from H28, rehearse | Logged timings in DEMO.md |
| N4 | after gate 4 | Underside flip pass merged into the splat (with C) | — |

### Role B: comparison engine
**Owns:** splat rendering at arbitrary poses; **reference registration** (coarse + fine + refine); anomaly maps; 3D lifting + clustering; identity check; handover localization + diff; Jev integration, fallback classifier, rules; evaluation + baselines. Code: `backend/compare/`, `backend/decide/`, `eval/` (metrics).

| # | Window | Task | Done when |
|---|---|---|---|
| B0 | pre | Jev access, API shape, latency; read gsplat camera-gradient support | Jev status known |
| B1 | H0–1 | `Comparator` class (DINOv2, ALIKED/SuperPoint + LightGlue, gsplat, SAM 2); `DecisionEngine` interface + `apply_rules` skeleton | Warm load OK |
| B2 | H1–3 | **Lighting risk first:** photo-only baseline vs references (homography) + primitives: histogram match in mask, DINOv2 patch distance, high-passed Lab, edge erosion. On real phone photos vs real references | Know early whether studio vs room lighting dominates |
| — | H3–6.5 | 💤 | — |
| B3 | H6.5–8 | Render the splat at keyframe poses (self-check: render ≈ photo); pre-render the coarse viewpoint sphere | Render-vs-photo overlays align |
| B4 | H8–10 | Coarse pose (DINOv2 global + silhouette) → fine (LightGlue + PnP with focal sweep) → render-and-optimize; `registration_progress` events | **★ H10:** IoU ≥ 0.85 on one object |
| B5 | H10–13 | Anomaly maps, persistence ≥ 2 refs, lift + HDBSCAN, region features + evidence, `candidates`; handover localization (PnP vs splat depth) + diff on one pair | **★ H13** |
| B6 | H13–16 | Identity score + wrong-reference test; `apply_rules` (thresholds, hard floor, price-neutral classes); RulesV0 → calibrated classifier; Jev with a 3 s timeout | Typed verdicts < 5 s per item; floor unit test |
| B7 | H16–20 | Latency: registration ≤ 15 s (parallel refs, cached spheres, ½-res refine), handover ≤ 20 s; label eval regions with D | Timed on 1 object |
| B8 | H20–26 | Eval: registration IoU + pose success rate; anomaly precision and recall vs references; handover precision and recall; false regions per clean scan; photo-only baseline; Jev vs LogReg (accuracy, ECE); latencies | **★ H26** numbers table to D |
| B9 | H26–29 | Live 3 of 3; N5 reliability chart | **★ H29** |

### Role C: capture and stage
**Owns:** Swift ARKit capture app (tap-to-anchor, AR dome, pose-tagged frames, live recognition display, upload, seller key); **stage view** with pipeline visualizations; **demo mode** and golden cache. Code: `ios/`, `web/app/stage/`, `web/lib/demo/`.

| # | Window | Task | Done when |
|---|---|---|---|
| C0 | pre | Mac, Xcode, iPhone, signing; LiDAR check; brand draft (mark, palette, type, seal) | App template runs on device |
| C1 | H0–1 | Xcode project on device; `ARSession` world tracking + plane detection; tap → raycast → anchor | **★ H1** |
| C2 | H1–3 | AR dome (RealityKit): 2 elevations × 12 azimuths; segment from anchor→camera direction; sharpness + motion gate; save JPEG (sensor orientation) + raw pose + scaled K + segment; lock exposure, focus, WB | Dome fills while walking around |
| C3 | H3–4 | Upload: `POST /scans`, signed URLs, first frame + `/first-frame` immediately, streaming 4 in flight, auto-complete at 90% | **★ H4** |
| C4 | H4–4.5 | Live recognition pop-up; `capture_progress` events | Model pops up mid-scan |
| — | H4.5–8 | 💤 | — |
| C5 | H8–10 | Stage view: dome mirror, splat reveal, **registration snap** (reference image floats, snaps, IoU ticks) | Snap plays from B's events |
| C6 | H10–13 | Stage: anomaly heatmap, **noise fade**, region glow, ledger build; demo **recorder**; app **handover mode** (10 s, `kind: handover`) | Live run recorded to JSONL |
| C7 | H13–16 | **Seller key** (CryptoKit Ed25519, Keychain), auto-seal on `passport_ready`, seller signing at handover; stage statement stack + handover red/amber + seal | Signature verifies in PyNaCl |
| C8 | H16–20 | Demo **player** (`?demo=`), "Replay" pill, offline build; full demo on a new object; **backup video** on two phones | **★ H20** |
| C9 | H20–33 | Stage polish (projector, reduced motion); release tag by H33 | Tagged |
| N4 | after gate 4 | Underside flip pass capture (with A) | — |

### Role D: product, money and trust
**Owns:** the Next.js app (sale page, passport viewer, review queue, statement, handover result, verify page); fair price engine + comps; signed records; Supabase schema; API skeleton (D16); contract regeneration; Devpost and pitch lead (all four rehearse). Code: `backend/api/`, `backend/price/`, `backend/record/`, `web/` (except stage + demo), `supabase/`, `contracts/`, `data/comps/`.

| # | Window | Task | Done when |
|---|---|---|---|
| D0 | pre | Hacker package (D9); comps with sources for demo objects + 8 batch items; accounts; script draft; sourced problem stats | Comps JSON ready |
| D1 | H0–1 | **Contract lock**: v3 schemas + generated types; Supabase migration; API stubs (all routes); `broadcast()` + `stage()` helpers; Next.js deployed; canonical JSON passes the vector in Python + TS | **★ H1** |
| D2 | H1–4 | Price engine test-first (determinism, traceability, floor, band); record builder; PyNaCl + tweetnacl; **CryptoKit interop test with C** | All three verify each other's signatures |
| D3 | H4–10 | Passport viewer (Spark: orbit, tilt, glowing regions, coverage badge, tap-for-photo via `/keyframe`, price breakdown); sale page skeleton; review queue; deals + join + buyer key | Opens from a QR on a phone |
| — | H10–13 | 💤 | — |
| D4 | H13–16 | Wire regions → price → ledger lines linked to regions; confirm/dismiss → re-price; choose price within band; publish sale page; listing record signed | **★ H16** |
| D5 | H16–20 | Household statement (cards + totals) with the 8-item batch; handover result (red/amber, wipe, buyer confirm, adjustment); verify page + tamper test | 5-item review < 1 min |
| D6 | H20–23 | Devpost: problem with sources, solution, architecture diagram, what's live vs cached, honest limits, extensions | **★ H23** |
| D7 | H23–34 | Numbers into the pitch (H26); rehearsals with injected failures; Q&A drill; final submission | **★ H32**, **★ H34** |
| N1–N3 | after gate 4 | Inbox agent; two-agent settlement; measure tool | — |

### Hand-off map

| Hand-off | From → to | By |
|---|---|---|
| Reference images + masks for demo objects | A → B | H1–H3 |
| Comps for demo objects + 8 batch items | D → price engine | H4 |
| API stubs + `broadcast()`/`stage()` helpers | D → all | H1 |
| CryptoKit ↔ PyNaCl ↔ tweetnacl interop | C ↔ D | H4 |
| Hand-held splat for early registration work | A → B | H4 |
| AR manifests (frames + poses) | C → A | H4 |
| Real AR splat + keyframes + `.ply` | A → B | H6 |
| `registration_progress` events | B → C | H10 |
| Regions + verdicts + identity | B → D, C | H13 |
| `/keyframe` tap-for-photo | A → D | H13 |
| Price + statement events | D → C | H16 |
| 8-item batch (real scans) | A → D | H18 |
| Golden recordings | A + C | H20 |
| Eval numbers table | B → D | H26 |

---

## 12. Repo layout and ownership

```
/
├── CLAUDE.md  ARCHITECTURE.md  DEMO.md      ← v3, current (D maintains; anyone fixes errors)
├── PRD.md  README.md  SPEC.md  plans/       ← v3 (each role owns its plan)
├── docs/diagrams/                           ← .mmd sources + rendered PNGs (edit .mmd, re-render; see its README)
├── contracts/                               ← SHARED, change via §7.3 (D runs regeneration)
│   ├── *.schema.json                        (v3 drafts, locked at H1)
│   ├── constants/price_v3.json              (D)
│   └── test-vectors/record_v3.json          (D)
├── ios/                                     ← C (Xcode project "Mint": capture, dome, upload, keys, Contracts/)
├── backend/
│   ├── contracts/models.py                  ← GENERATED
│   ├── api/                                 ← D (FastAPI app, DB, realtime + stage helpers); owners add routes
│   ├── recon/                               ← A (Reconstructor, recognition, keyframes)
│   ├── compare/                             ← B (Comparator: render, registration, anomaly, identity, handover)
│   ├── decide/                              ← B (DecisionEngine, RulesV0, classifier, Jev, apply_rules)
│   ├── price/                               ← D (price engine, statement, adjustment)
│   └── record/                              ← D (canonical JSON, hashing, signature verification)
├── web/                                     ← D (product pages) …
│   ├── app/stage/  lib/demo/  public/demo/  ← … except these: C (stage view, demo player, golden assets)
│   ├── lib/contracts.ts                     ← GENERATED
│   └── lib/crypto/                          ← D (canonicalise, sha256, buyer key, sign, verify)
├── data/refs/{model_key}/                   ← A (reference images + masks + refs.json with sources)
├── data/comps/{model_key}.json              ← D (comps with sources)
├── supabase/migrations/                     ← D
├── eval/                                    ← B (metrics, baselines, charts) + D (labels, capture log)
├── fixtures/index.json                      ← everyone (files live in the `fixtures` bucket)
└── demo/{key}/                              ← golden recordings (A records, C plays)
```

---

## 13. Fixtures and evaluation

**Fixture discipline:** only real scans and real reference images. Raw frames live in the Supabase `fixtures` bucket; `fixtures/index.json` lists each (`key, object, kind, change, captured_by, captured_at, notes`). References always carry their source URL.

**Dataset (D captures with A, B consumes):** 3–5 matte, textured objects with official reference images. Per object: **1 listing scan**, **3 handover scans with logged changes**, **2 no-change rescans**. **Existing wear on each object is logged by hand** (location + photo).

**Region labels:** regions overlapping logged wear or logged changes are positive; all others are artifacts.

**Metrics:** registration silhouette IoU + pose success rate · anomaly precision and recall vs references · handover precision and recall · false regions per clean scan · latencies (scan → passport, registration + comparison, handover).

**Baselines:**
1. **Photo-only vs references:** homography-align a real photo to each reference and diff, vs splat render-and-compare. Report false regions for both.
2. **Jev vs calibrated logistic regression** on the same region features: accuracy + ECE.

**Honesty:** the pitch states the dataset size and that thresholds were tuned on it.

---

## 14. Development workflow

### 14.1 Environment

| Variable / secret | Used by | Secret? | Where |
|---|---|---|---|
| `MINT_ROLE` | Claude Code (§1) | no | shell profile |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | backend **only** | **YES** | Modal secret `mint-supabase` |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL` | web | public | Vercel env + `web/.env.local` |
| `MINT_API_URL` | iOS app | no | `ios/Config.xcconfig` (no secrets in the app) |
| VLM key (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`) | recognition (A); N1/N2 agents (D) | yes | Modal secret `mint-llm` |
| `JEV_API_KEY` (name TBD) | decisions (B) | yes | Modal secret `mint-jev` |

Commit `.env.example` files with names only. Never commit keys. If one leaks, rotate it and tell the team.

### 14.2 Commands (expected; confirm at H1)

| Task | Command |
|---|---|
| Dev API | `modal serve backend/api/app.py` |
| Deploy | `modal deploy backend/api/app.py` · `modal deploy backend/recon/app.py` · `modal deploy backend/compare/app.py` |
| Backend tests | `pytest backend -q` |
| Web | `cd web && pnpm dev` · offline demo: `pnpm build && pnpm start` · tests: `pnpm test` |
| iOS | Open `ios/Mint.xcodeproj`, run on device (⌘R); tests ⌘U |
| DB | `supabase db push` |
| Diagrams | see [docs/diagrams/README.md](docs/diagrams/README.md) |

### 14.3 Git

Trunk-based on `main`, always deployable · `git pull --rebase` before every push · small commits at least hourly · prefixes `A:` `B:` `C:` `D:` `contracts:` `docs:` `demo:` · never force-push `main` · no secrets, weights or files > 5 MB (frames and splats go to Storage) · Vercel auto-deploys `main`; each GPU class is deployed by its owner after tests pass · tag `v1.0-demo` by H33 (C).

### 14.4 Code style

- **Python 3.11**, type hints, Pydantic v2 at boundaries, `ruff`. Pure logic in small pure functions with table tests. GPU classes load models once in `@modal.enter`.
- **TypeScript strict**, Next.js App Router, pnpm; no `any` at contract boundaries.
- **Swift**: SwiftUI + RealityKit, async/await for uploads, `Codable` contracts, no force-unwraps on network paths, keys only in the Keychain.
- Every pipeline step is wrapped in `stage("name")`. User-facing copy follows the brand voice; errors are plain language ("Too blurry. Slow down a little.").

---

## 15. Brand and experience

**Name:** Mint ("mint condition" + minting a verified record). **Motif:** a minted seal for verified passports, a stamp when records are signed, subtle banknote guilloche on statements and verify pages.

| Token | Use | Value |
|---|---|---|
| `--mint` | accent, verified, coverage badge | `#3DDC97` |
| `--stage-bg` | near-black stage | `#0B0F0E` |
| `--paper` | warm off-white phone pages | `#FAF7F2` |
| `--amber` | **disclosed** regions | `#F5B53F` |
| `--red` | **new damage** at handover | `#FF4D4D` |
| `--slate` | artifacts | `#8A9499` |

Layout and component rules: [docs/design/DESIGN.md](docs/design/DESIGN.md). Light mode only.

**Voice:** calm, short, slightly witty. "Found 2 real marks. Ignored 31 lighting differences." · "Coverage verified. Nothing hidden." · "Sealed. Nobody can quietly edit this."

**Make the tech visible (stage view, C):** dome filling + model pop-up → splat reveal → **reference snaps into alignment with IoU ticking up** → heatmap, noise fades, real wear glows → ledger lines build, band narrows → item cards stack into the household total → red beside amber + wipe slider → stamp, QR, verify sweep. A live per-stage timing bar is always on.

**Screens:**

| Screen | Where | Owner |
|---|---|---|
| Capture (dome, model pop-up, coverage, upload) | iOS app | C |
| Seller review queue | `/review/[batchId]` (phone) | D |
| Sale page | `/s/[batchId]` | D |
| Passport | `/p/[itemId]` | D |
| Household statement | `/statement/[batchId]` | D |
| Handover result (buyer confirms + signs) | `/h/[dealId]` | D |
| Verify | `/v/[recordId]` | D |
| Stage view | `/stage/[batchId]`, `/stage/deal/[dealId]` | C |

Tools: Spark (three.js), Framer Motion, SVG for the dome mirror and seal. Quality bar: smooth splat on a mid-range iPhone in Safari · readable at arm's length on a projector · contrast, focus states, `prefers-reduced-motion`.

---

## 16. The demo (summary; full runbook in [DEMO.md](DEMO.md))

| Time | Beat | Live or cached |
|---|---|---|
| 0:00–0:20 | **Hook:** "Pawnshops pay a fraction of what your things are worth because they can't trust condition." | Live |
| 0:20–0:55 | **Scan:** AR dome fills, model pops up | Live capture; splat from an earlier scan of the same item ("training takes about 90 seconds; here's this item scanned earlier") |
| 0:55–1:45 | **Registration + condition:** manufacturer images snap on; heatmap; noise fades; wear glows; identity passes | **Live on the cached splat** (~15 s) |
| 1:45–2:20 | **Fair price band:** ledger builds; seller confirms one uncertain region | Live |
| 2:20–2:45 | **Garage sale:** household statement for the pre-baked 8-item batch; judges open the sale page QR | Cached data, live viewing |
| 2:45–3:35 | **Handover:** judge adds a sticker + marker line; 10 s rescan; red beside amber; wipe; judge signs | **Live** (~20 s) |
| 3:35–4:00 | **Close:** proof numbers + "Mint makes your belongings verifiable, priceable and liquid." | Live |

**Integrity:** the Replay pill shows on cached steps; if asked, state exactly what was live, with real timings.

---

## 17. Risks and fallbacks

| Risk | Fallback | Owner |
|---|---|---|
| Studio vs phone lighting dominates the comparison | Histogram match in mask, DINOv2, high-pass, ≥ 2-reference persistence; **tested H1–H3** on one object | B |
| References are renders or the wrong variant | Curate for demo objects; keep only refs with IoU ≥ 0.85 | A, B |
| Registration fails on symmetric objects | Multiple references; choose asymmetric demo objects | A, B |
| Registration fails on one reference (live) | Skip to the next reference | B |
| AR app takes too long | C starts at H0; Object Capture or hand-held fallback **decided by H6** | C |
| Splat misses 100 s | Warm GPU, fewer frames and iterations; cached splat already in the script | A |
| Handover localization fails | Rescan slower; else golden result | B |
| Jev access or latency | Fallback classifier by H16 | B |
| CryptoKit ↔ tweetnacl mismatch | Interop test by H4; fallback: sign in a web view with tweetnacl | C, D |
| Splat stutters on phone | Lower Gaussian cap; lower pixel ratio | A, D |
| Wi-Fi down | Hotspot → demo mode (local `pnpm start`) | C |
| Laptop fails | Backup video (H20) on two phones | C |
| Scope | Gates, freeze at H20, stretch only after gate 4 | everyone |

---

## 18. Pre-hack checklist (before Fri Oct 16, 10 PM ET; no project code)

| ✓ | Item | Who |
|---|---|---|
| [ ] | Confirm Jev access + latency | B |
| [ ] | Build the Modal GPU image (throwaway); time one splat on L4 and A100 → D12 | A |
| [ ] | VLM benchmark on demo-object photos → D13 | A |
| [ ] | Mac + Xcode + iPhone ready; device signing; **does anyone have a LiDAR iPhone?** | C |
| [ ] | 3–5 matte, textured, **asymmetric** demo objects with official reference images; references saved with sources | A |
| [ ] | Comps with sources for demo objects + the 8 batch items | D |
| [ ] | 8 items available for the garage-sale batch | all |
| [ ] | Sticker sheet + marker for the handover demo | D |
| [ ] | Brand draft: mark, palette, type, seal | C |
| [ ] | Hacker package: judging time, prizes, pre-hack rules (D9) | D |
| [ ] | Roles confirmed; `MINT_ROLE` set in every shell | all |

---

## 19. Glossary

| Term | Meaning |
|---|---|
| **3D Gaussian splat** | A 3D scene made of many small coloured, semi-transparent blobs, trained from photos; renders photorealistically from any angle |
| **Passport** | An item's splat + keyframes + condition + price band + coverage badge + sealed hash, viewable from a QR |
| **AR dome / segment** | The capture guide: segments at two elevations around the anchor; each fills when a sharp frame is captured from that direction |
| **Anchor / scan frame** | The tapped point on the surface / the listing scan's ARKit world re-centred on it, +Y up, metres |
| **Coverage-verified** | ≥ 90% of dome segments filled, so the seller couldn't hide a side |
| **Hand filter** | Drops frames where a hand overlaps the item mask |
| **Reference image** | An official manufacturer photo of the same model and variant |
| **Registration** | Solving the reference photo's camera pose (and focal length) relative to the splat |
| **Coarse / fine pose / render-and-optimize** | Viewpoint-sphere matching / feature matching + PnP / gradient refinement on silhouette IoU through the differentiable renderer |
| **Silhouette IoU** | Overlap between the reference's product mask and the render's alpha at the solved pose (≥ 0.85 to accept) |
| **Anomaly map** | Per-pixel difference after normalization: DINOv2 patch distance + high-passed Lab difference |
| **High-pass** | Removing smooth lighting gradients so only local marks remain |
| **Persistence** | An anomaly must appear in ≥ 2 references to become a region |
| **Region / candidate** | A clustered 3D area of change with features / a pre-clustering changed point (the dots that fade) |
| **Verdict / decision** | Class + severity (+ present-before) probabilities / `accepted`, `needs_confirmation`, `uncertain`, `dropped` |
| **Hard floor** | Code rule: a region measured in ≥ 70% of the views that see it can't be dropped as an artifact |
| **Identity match** | Score from silhouette + geometric agreement with references; low → mismatch warning |
| **Comps / market value** | Comparable used sales (curated, sourced) / their median |
| **Condition / price band / ledger** | 1 − Σ penalties / mid ± width that grows with uncertainty / one deduction line per region |
| **Review queue** | Seller swipes items, confirms or dismisses flagged regions, sets a price within the band |
| **Household statement / sale page** | All batch items with condition, band, price and totals / the public page for the batch |
| **Disclosed vs new** | At handover: amber = already in the listing; red = new since listing |
| **Adjustment** | Deterministic price difference caused by new handover damage |
| **Record / seal** | Canonical, integer-only JSON signed with Ed25519 / the act of signing |
| **Golden asset / Replay** | A recording of a real run / the always-visible cached-step indicator |
| **Jev (TypeSafe)** | External typed-question decision engine; primary if access is confirmed |
| **RulesV0 / FallbackClassifier** | Heuristic engine for early integration / calibrated LogReg + GBR baseline |
| **H-hour / checkpoint / gate** | Hours since H0 / timed pass-or-fail call / demoable milestone |

---

## 20. Document map

| Doc | Status | Use it for |
|---|---|---|
| **CLAUDE.md** | v3 ✅ | The game plan (this file) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | v3 ✅ | Diagrams, conventions, pipeline internals, price engine, records, contracts, API, events, data, deployment |
| [DEMO.md](DEMO.md) | v3 ✅ | Pitch script, golden assets, runbook, Q&A, rehearsal log |
| [docs/diagrams/](docs/diagrams/) | v3 ✅ | Diagram sources and PNGs |
| [contracts/](contracts/) | v3 ✅ draft (lock at H1) | JSON Schemas, price constants, test vector |
| [PRD.md](PRD.md) | v3 ✅ | Requirements, metrics, open questions, risks |
| [plans/](plans/) | v3 ✅ | Per-role tasks, interfaces, fixtures, fallbacks |
| [README.md](README.md) | v3 ✅ | Short overview for newcomers |
| [SPEC.md](SPEC.md) | v3 ✅ | The team's source spec, verbatim |

*If anything contradicts this file, this file wins. Fix the other doc and tell the team.*
