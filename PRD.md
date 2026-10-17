# Mint — Product Requirements Document (v3)

*Mint makes your belongings verifiable, priceable and liquid.*
Hack the Valley 11 · Theme: Sustainable FinTech & Economic Inclusion · H0 = Fri Oct 16 2026, 10:00 PM ET → H34 = Sun Oct 18, 8:00 AM ET

> Requirements only: **what** must be true and **why**. The **how** is in [ARCHITECTURE.md](ARCHITECTURE.md); owners and schedule are in [CLAUDE.md](CLAUDE.md) and [plans/](plans/). Source spec: [SPEC.md](SPEC.md).

---

## Problem

**Condition is the unpriced variable in second-hand money.** Model and age are easy to look up; condition isn't, so every second-hand transaction is discounted for uncertainty. People with the least leverage lose most: pawnshops and resale stores pay a fraction of value, lowballers exploit sellers who don't know what their item is worth, buyers get burned by hidden damage and fakes, and households sit on hundreds of dollars of unused belongings because pricing and listing each item is too much work. Photos can't fix it: they never match a reference image's angle or light, so condition can't be measured from them.

## Evidence

- Assumption: pawnshops and resale stores pay well below fair value for used goods. *Validate with a sourced statistic (D, before H23).*
- Assumption: lowballing and condition misrepresentation are common on peer-to-peer marketplaces. *Validate with sourced reports or forum evidence (D).*
- Assumption: households hold significant unused, resellable value. *Validate with a sourced estimate (D).*
- First-hand (will exist by H26): our **photo-only baseline** shows how many false regions a photo comparison against references produces vs Mint's splat render-and-compare.

> No statistic goes into the pitch without a URL.

## Users

- **Primary: a household seller** with a closet of unused items (electronics, gear, accessories) who doesn't know what each is worth and is likely to be lowballed or underpaid by a pawnshop. Trigger: needs cash or space, decides to sell.
- **Primary: a second-hand buyer** who depends on used goods and needs to trust condition and identity before paying, and to catch transit damage at delivery. Trigger: considering a listing, or receiving a delivery.
- **Secondary (pitch only):** pawnshops and resale stores wanting objective intake grading; lenders who could use verified records as collateral (micro-loan extension).
- **Not for:** shiny, glass or transparent items; heavily customized items without references; real payments, escrow or marketplace posting; counterfeit certification.

## Hypothesis

We believe **an AR-guided 3D scan compared against the manufacturer's own reference images, turned into a traceable fair price band**, will **remove the condition information gap that lets pawnshops and lowballers underpay** for **people selling and buying second-hand**.

We'll know we're right (hackathon scale) when:
1. Reference images **register onto the splat with silhouette IoU ≥ 0.85** and known wear is found with **≤ 2 false regions per clean object**, beating a photo-only baseline.
2. The **same inputs always give the same price band**, and every dollar traces to a region or a comp.
3. A **5-item batch** can be reviewed in under a minute and an **8-item household statement** renders as one sale page.
4. At handover, a judge **sees new damage in red beside disclosed amber** within 20 s and **signs on their own phone**.

## Success metrics

| Metric | Target | How measured |
|---|---|---|
| Scan → passport | ≤ 100 s, 3 of 3 demo objects | `stage` timing events |
| Live recognition | Model on screen ≤ 5 s, 3 of 3 | Timestamps |
| AR coverage | 90% in 20–25 s, 3 of 3 | App telemetry |
| Registration | IoU ≥ 0.85 on ≥ 3 refs per object; report mean IoU and pose success rate | Eval |
| Registration + comparison | ≤ 15 s per item | Timing |
| Condition detection | Known wear found; ≤ 2 false regions per clean object; precision and recall reported | Eval |
| Identity check | Correct model passes; wrong reference set warns | Eval |
| Handover | Sticker + marker found; ≤ 2 regions on no-change; ≤ 20 s; precision and recall | Eval |
| Baselines | Photo-only false regions vs Mint; Jev vs logistic regression accuracy + ECE | Eval |
| Price engine | Deterministic; 100% of dollars traced | Unit tests |
| Review speed | 5 items < 1 min | Stopwatch |
| Record integrity | 1-byte edit fails; signatures from 2 devices | Verify page |
| Demo | 3 clean timed rehearsals by H32 | DEMO.md log |

## Scope

**MVP (must-haves).** Owner and gate details: [CLAUDE.md §5](CLAUDE.md#5-every-feature).

| ID | Requirement | Acceptance criteria |
|---|---|---|
| M1 | AR-guided capture (tap → dome → two heights → pose-tagged frames → auto-upload at ~90%) | 20–25 s scan hits 90% on 3 of 3; frames + poses stored |
| M2 | Live recognition (one VLM call: label, brand, model, variant, category, box) | Model shown ≤ 5 s, 3 of 3 |
| M3 | Object isolation (SAM 2; hand frames dropped) | Splat contains only the item |
| M4 | Splat (ARKit + VGGT poses, gsplat, web export, keyframe index, metric scale) | Scan → passport ≤ 100 s |
| M5 | Reference retrieval (3–5 official images; curated for demo objects) | Present for 3 of 3 |
| M6 | Reference registration (coarse → fine → render-and-optimize) | IoU ≥ 0.85 on ≥ 3 refs per object |
| M7 | Condition vs references (normalised, multi-reference-persistent anomalies → 3D regions) | Known wear found; ≤ 2 false regions per clean object |
| M8 | Identity check (match score + mismatch warning) | Correct passes; wrong refs warn |
| M9 | Decisions (Jev or fallback; code thresholds, hard floor, confirmation routing) | Typed verdicts < 5 s per item |
| M10 | Fair price band (comps × condition; band grows with uncertainty; deductions linked to regions) | Deterministic; every dollar traced |
| M11 | Seller review queue (confirm/dismiss, price within band) | 5 items < 1 min |
| M12 | Garage sale mode + household statement + sale page | Renders for a pre-baked 8-item batch |
| M13 | Passport viewer (orbit, tilt, regions, coverage badge, tap-for-photo, price breakdown; QR, no app) | Judge inspects on own phone |
| M14 | Handover check (localize into seller splat, compare, red new vs amber disclosed) | Sticker + marker found; ≤ 2 on no-change; ≤ 20 s |
| M15 | Signed records (canonical JSON, SHA-256, Ed25519 on iPhone + browser; verify page) | 1-byte edit fails; 2 devices |
| M16 | Pipeline stage view (registration snap, heatmap, noise fade, price build, statement, handover, seal) | Plays live and cached |
| M17 | Demo mode (golden cache, Replay indicator) | Full demo offline |
| M18 | Evaluation (labelled set, P/R, registration accuracy, baselines) | Numbers by H26 |

**Nice-to-have (only after gate 4):** N1 inbox agent · N2 two-agent settlement · N3 measure tool · N4 underside flip pass · N5 calibration chart.

**Out of scope**
- Real payments or escrow: regulatory scope; the micro-loan idea is a pitch extension only.
- Real marketplace posting: no APIs; terms of service.
- Turntables, marker boards or extra hardware: the product must work with just a phone.
- On-device splat training; blockchain: unnecessary for the hypothesis.
- Shiny, glass or transparent demo objects: known splat weakness.
- Counterfeit certification: we only warn on mismatch.

## Delivery milestones

| # | Milestone | User-visible outcome | Target | Status |
|---|---|---|---|---|
| 1 | Scan → passport | AR scan becomes a viewable 3D passport | H4 → H6 | pending |
| 2 | Condition vs references | Manufacturer images snap onto the model; real wear glows | H10 → H13 | pending |
| 3 | Priced and listed | Price band, review queue, sale page | H16 | pending |
| 4 | Handover and proof | Red vs amber at handover; signed record verifies | H13 → H16 | pending |
| 5 | Show the tech | Stage visualizations, brand, demo mode offline, rehearsals | H20 → H32 | pending |
| 6 | Stretch | N1–N5, one at a time | after gate 4 | pending |

## Open questions

- [ ] **Jev (TypeSafe)** access, API shape and latency (B, pre-hack).
- [ ] **Hacker package:** is pre-hack curation of references and comps allowed (D9)? Judging time, prizes (D).
- [ ] **GPU type** L4 vs A100 for the 100 s budget (A, D12).
- [ ] **Recognition VLM** choice by latency and model/variant accuracy (A, D13).
- [ ] **LiDAR iPhone** available for the Object Capture fallback? (C)
- [ ] **Demo objects:** which 3–5 have good official reference images of the exact variant and are matte, textured and asymmetric? (A)
- [ ] **Price constants** (weights, floor, band) tuned against real comps (D, D11).
- [ ] Do studio-vs-room lighting differences dominate the anomaly map? Answered by B's H1–H3 test.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Lighting differences dominate comparison | Med | High | Histogram match in mask, DINOv2, high-pass, ≥ 2-reference persistence; tested H1–H3 |
| References are renders or the wrong variant | Med | High | Curate; keep only IoU ≥ 0.85 |
| Registration fails on symmetric objects | Med | Med | Asymmetric demo objects; multiple references |
| AR app slow to build | Med | High | C starts at H0; fallback decided by H6 |
| Splat misses 100 s | Med | Med | Warm GPU, fewer iterations; cached splat in the script |
| Jev unavailable | Med | Low | Calibrated classifier by H16 |
| CryptoKit ↔ tweetnacl mismatch | Low | Med | Interop test by H4 |
| Scope creep | High | High | Gates, freeze at H20, stretch after gate 4 |

---
*Status: DRAFT v3. Implementation plans: [plans/](plans/) and [CLAUDE.md §11](CLAUDE.md#11-roles-in-detail).*
