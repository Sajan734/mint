# Mint — Demo runbook (v3)

**4-minute pitch + 1 minute Q&A.** Pitch line: *"Mint makes your belongings verifiable, priceable and liquid."*
The plan is in [CLAUDE.md](CLAUDE.md) and the system in [ARCHITECTURE.md](ARCHITECTURE.md). Fill every `[TBD @H26]` with real numbers from B's eval and the timed rehearsals. **Never round in our favour.**

**Show the tech.** The judges should *see* the pipeline (dome filling, references snapping on, noise fading, ledger building, red beside amber), not just the result. The stage view does this; the speakers point at it.

---

## 1. Cast and devices

| Who | Device | Role in the demo |
|---|---|---|
| **D** (pitch lead) | Clicker / laptop keyboard | Hook, price band, garage sale, close; owns the clock |
| **C** | **Capture iPhone** (Mint app, **seller key** in the Keychain) | Runs the live AR scan and the handover rescan; taps "confirm" in the review queue |
| **B** | — | Narrates registration + condition (0:55–1:45) and the handover check (2:45–3:35) |
| **A** | **Stage laptop** → projector, `/stage/{batchId}` then `/stage/deal/{dealId}` | Drives the stage view, switches to golden keys if needed, watches the timing bar; leads 3D questions in Q&A |
| Judge | Their own phone (**buyer key** generated when they open the deal QR) | Opens the sale page, inspects items, signs the handover |
| Spare | Backup laptop (offline build) + **spare phone** for a judge who can't scan a QR | — |

Speaker split is decision D17 (PROPOSED); everyone rehearses every beat in case someone is unavailable.

## 2. Script

| Time | Who | Beat | On screen (stage) | Live or cached | Must be true |
|---|---|---|---|---|---|
| 0:00–0:20 | D | **Hook:** "Pawnshops pay a fraction of what your things are worth because they can't trust condition. Lowballers count on you not knowing. Photos don't fix it; you can't measure condition from a flattering angle." | Mint logo, the item on the table | Live | — |
| 0:20–0:55 | C (D narrates) | **Scan.** C taps the item and the AR dome anchors. C walks around at two heights; segments fill; **brand + model pop up mid-scan**. D: "Training takes about 90 seconds, so here's this same item scanned earlier." A switches the stage to the cached splat: points densify into the photoreal item. | Dome mirror → model pop-up → splat reveal; **Replay pill on the splat** | Live capture; **cached splat** of the same item | Model shows ≤ 5 s |
| 0:55–1:45 | B | **Registration + condition.** "These are Sony's official product photos. We solve where each photo's camera was, relative to our 3D model…" Each reference **floats over the model and snaps into alignment**, IoU ticking up. Heatmap appears; "dozens of candidates are just lighting; they don't persist across references, so they fade." Real wear stays and glows. "The identity check passes: it really is a WH-1000XM4." | Registration snap ×3–5, heatmap, noise fade, glowing regions, identity badge | **Live on the cached splat** (~15 s) | IoU ≥ 0.85 on ≥ 3 references |
| 1:45–2:20 | D (C taps) | **Fair price band.** "Market value comes from real comparable sales; here are the sources. Every deduction is a line tied to a glowing region." Ledger builds line by line. "One region is uncertain, so Mint asks the seller." C confirms it in the review queue → **the band narrows**. | Comps → market value → ledger lines → band; band narrows on confirm | Live | Same inputs → same band |
| 2:20–2:45 | D | **Garage sale.** "Most people don't have one thing to sell; they have a closet. Here's a household of 8 items we scanned earlier." Cards stack into the **household total**. "Scan the QR; inspect anything on your own phone." | Statement stacking into a total; sale page QR | **Cached data, live viewing** (Replay pill on the statement) | Judges' phones open the sale page |
| 2:45–3:35 | B (C rescans) | **Handover.** "Now say it's being delivered." The judge opens the deal QR (buyer key created) and **adds a sticker and a marker line**. C does a 10 s rescan. "We place every new photo inside the seller's 3D model and render the exact same view." **New regions glow red beside the amber ones** the seller disclosed. Judge drags the **wipe slider**. "The sticker is removable, so it's noted but doesn't change the price; the marker line is new damage." The judge **signs on their phone**, C signs on the iPhone, **stamp**, verify QR. | Localization, red beside amber, wipe slider, adjustment, stamp, verify check sweep | **Live** (~20 s) | Both regions found; ≤ 20 s; 2 signatures |
| 3:35–4:00 | D | **Close:** "On our labelled set: registration IoU [TBD @H26], precision [TBD @H26] and recall [TBD @H26], and [TBD @H26]× fewer false regions than comparing photos. Mint makes your belongings verifiable, priceable and liquid." | Proof-numbers card, logo | Live | Numbers are real and sourced from the eval |

**Off-screen setup during the pitch:** none. Everything is set up before the judges arrive (§5).

## 3. Live vs cached, and what we say

| Step | Live? | If a judge asks |
|---|---|---|
| AR capture + live recognition | ✅ live | "That was live." |
| Splat of the scanned item | ❌ cached (scanned earlier, same item) | "Training takes about [TBD @H26] seconds on our GPU, so we showed the same item scanned earlier. Here's the live one finishing now." (if it has) |
| Registration + condition + identity | ✅ live, on the cached splat | "Live, about [TBD @H26] seconds." |
| Price band + review confirm | ✅ live | "Live and deterministic: same inputs, same band." |
| 8-item household statement | ❌ cached data (real scans from earlier); viewing is live | "Those are 8 real scans from Saturday; the page you're holding is live." |
| Handover rescan → result → signatures | ✅ live | "Live, [TBD @H26] seconds end to end." |

**Integrity rules:** the **Replay pill** is visible on every cached step and can't be hidden · we only switch to golden results with a spoken line · if asked, state exactly what was live and give the real timings from the stage's timing bar.

## 4. Golden assets (recorded from real runs, H16–H20)

| Key | Contents | Used for |
|---|---|---|
| `item-live` | Passport of **the item we scan live** (splat, keyframes, references, registration + condition run, price) | The 0:20 splat; fallback for 0:55 if registration fails live |
| `obj-2`, `obj-3` | The other demo objects, full Pipeline 2 + price | Q&A ("show another one"), fallback |
| `batch-8` | **8 real scans**: passports, conditions, prices, statement, sale page | 2:20 garage sale |
| `handover-golden` | A real handover run on `item-live` (sticker + marker) with both signatures | Fallback for 2:45 |
| `wrong-ref` | Identity check against a deliberately wrong reference set (warning fires) | Q&A on counterfeits |

Each folder holds `events.jsonl` (realtime envelope + `t_ms`), splats, thumbs, reference images (with sources), renders, anomaly maps, wipe pairs, records and `timings.json`. Replays use the original timings.

## 5. Pre-show checklist (T−30 min)

| ✓ | Item | Who |
|---|---|---|
| [ ] | `GET /healthz/warm` returns warm for `Reconstructor` + `Comparator`; `min_containers=1` | A |
| [ ] | Stage laptop on `/stage/{batchId}`, projector mirrored, timing bar visible, Replay pill shows on a cached test | A |
| [ ] | Demo item **clean** (no sticker or marker from rehearsal); same condition as `item-live` | C |
| [ ] | Sticker sheet + marker on the table | D |
| [ ] | Capture iPhone charged, Mint app open, seller key present, exposure test done in the room's light | C |
| [ ] | Deal for `item-live` pre-created; deal QR + sale page QR on the stage and printed | D |
| [ ] | Phone hotspot on and tested; venue Wi-Fi tested | C |
| [ ] | Backup laptop running the offline build (`pnpm start`) with all golden keys | C |
| [ ] | Backup video on two phones | C |
| [ ] | Spare phone ready for a judge who can't scan | D |
| [ ] | Timer visible to D | D |

## 6. Failure runbook

| Failure | Detect | Say | Do | Owner |
|---|---|---|---|---|
| AR app crashes or won't anchor | No dome after 3 s | "Let me try that again." | Relaunch once; then play the `item-live` capture recording | C |
| Recognition slow | No pop-up by ~0:30 | (nothing) | Carry on; the label arrives with the passport | A |
| Registration fails on a reference | `registration` status `failed` | "That photo's a different angle we can't match. Skipping it." | Automatic skip to the next reference | B |
| Registration fails on all references | < 3 accepted | "Here's the run from earlier." | Switch to the `item-live` cached condition run (Replay pill) | A |
| Price engine error | `error` event | (nothing) | `item-live` cached price | D |
| Judge can't open a QR | — | "Use this one." | Hand them the spare phone | D |
| Handover localization fails | `error` at localize | "Let me rescan a little slower." | One slower rescan; else `handover-golden` | B, C |
| Handover over 20 s | Timing bar | Fill: explain amber vs red while it runs | Wait up to ~30 s; else `handover-golden` | B |
| Judge's signature fails | No `signature` event | "Let's use our test phone for the buyer." | Spare phone signs | D |
| Jev slow or down | Engine chip shows `fallback` | (only if asked) "We run a calibrated classifier as a fallback." | Automatic | B |
| Wi-Fi down | Uploads stall | "Switching to our hotspot." | Hotspot → if still down, offline build with golden keys | C |
| Laptop dies | — | — | Backup laptop; else the backup video on two phones | A, C |

## 7. Numbers for the pitch (fill at H26; never round up)

| Metric | Value | Source |
|---|---|---|
| Scan → passport (median of N runs) | [TBD @H26] s | Stage timings |
| Registration + comparison per item | [TBD @H26] s | Stage timings |
| Handover check (median) | [TBD @H26] s | Stage timings |
| Registration: mean silhouette IoU / pose success rate | [TBD @H26] / [TBD @H26] | Eval |
| Condition vs references: precision / recall | [TBD @H26] / [TBD @H26] | Eval |
| False regions per clean scan: Mint / photo-only baseline | [TBD @H26] / [TBD @H26] | Baseline 1 |
| Handover: precision / recall | [TBD @H26] / [TBD @H26] | Eval |
| Jev vs logistic regression: accuracy / ECE | [TBD @H26] | Baseline 2 |
| Identity check: correct passes / wrong refs warn | [TBD @H26] | Eval |
| Dataset size | [TBD] objects, [TBD] scans, [TBD] labelled regions | Eval |

## 8. Q&A answers

| Question | Answer |
|---|---|
| **Why not compare photos to the stock image?** | Angles never match. We solve the reference camera's pose against the splat and render the exact same view. Photo-only baseline: [TBD @H26] false regions vs [TBD @H26] for Mint. |
| **Studio vs room lighting?** | Colour normalization inside the product mask, lighting-tolerant DINOv2 features, high-pass local differences, and an anomaly must persist across at least two references. |
| **Who decides what's damage?** | Mint measures and flags; sellers confirm flagged regions before publishing; buyers can inspect any angle themselves. Uncertain findings never move the price. |
| **Is the price fair?** | Comparable sales × measured condition. Every deduction is a line tied to a region you can tap, and the band widens when we're less sure. Same inputs always give the same band. |
| **Where do the comps come from?** | Curated comparable used sales for our demo objects, with sources listed. Live retrieval is future work. |
| **Counterfeits?** | We flag geometric mismatch with the reference model. That's a warning, not authenticity certification. |
| **Can a seller hide the bad side?** | Not with a coverage-verified scan: the dome only completes when every side was seen. |
| **Can a model hide damage?** | No. If a change is measured consistently in at least 70% of the views that see it, no model can drop it as noise. |
| **Can someone fake a scan or edit the record?** | Records are hashed and signed on both devices; one changed byte fails verification. That proves integrity after capture; device attestation and C2PA would prove the capture itself. |
| **How accurate is it?** | Numbers on our labelled set: [TBD @H26], with its size stated, and thresholds were tuned on it. |
| **What doesn't work?** | Shiny, glass and transparent items; heavily customized items without references. |
| **Why 3D and not just more photos?** | Only a 3D model can be re-rendered from the exact angle of a reference photo or a buyer's photo. That's what makes like-for-like comparison possible. |
| **Why Jev (or a classifier) and not an LLM?** | Many regions per item need typed answers with calibrated probabilities in seconds, from measured features. We compared Jev against a simple calibrated classifier: [TBD @H26]. |
| **What's the financial-inclusion angle beyond selling?** | A verified condition record lets possessions serve as collateral for fair micro-loans instead of predatory pawn rates. That's our next step, not built yet. |
| **What was live and what was cached?** | §3, stated plainly with real timings. |

## 9. Rehearsal log

Run every rehearsal with the timer, and inject one failure from §6 each time.

| # | Time (H) | Total | Recognition (s) | Registration (s) | Handover (s) | Injected failure | What went wrong / fix |
|---|---|---|---|---|---|---|---|
| 1 | ~H26 | | | | | | |
| 2 | ~H29 | | | | | | |
| 3 | ~H31 | | | | | | |
