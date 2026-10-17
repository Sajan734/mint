# Fixtures

One folder per test item:

```
itemNN/
  input.json       what the seller provides (seller_name, may be null; optional asking_price_cad)
  expected.json    the outcome the pipeline should reach
  stubs/<stage>.json
  views/           real renders go here (not yet captured)
  baseline.jpg     optional manual baseline photo (.jpg, .jpeg or .png)
  baseline.json    {"source_url": "..."} for the manual baseline
```

**Manual baseline for demos:** put a real, sourced product photo in the item folder as `baseline.jpg` (or `.png`) with its `source_url` in `baseline.json`, then run with `--manual-baseline` or `MANUAL_BASELINE=1`. In that mode `baseline_lookup` never searches. If the photo is too large it is shrunk into `runs/` to fit Jev's limits; if it is missing or unusable the match is treated as uncertain. item01 and item02 have no manual baseline yet.

**The `stubs/` data is hand-written placeholder data, not real model output.** Each stubbed stage loads `stubs/<stage>.json` instead of calling Gemini or Jev. Replace a stub with recorded real output once that stage is implemented. The prices are not real comps and have no source URL. The image paths point to files that don't exist yet.

| Item | Scenario | Expected |
|---|---|---|
| item01 | Used black Sony WH-1000XM4 with light wear, no seller name, no asking price | `Listing`, deal rated `fair` (Mint's suggested price), no highlighted splat |
| item02 | Seller typed "Sony WH-1000XM4", but the scan is a Bose QuietComfort 45 | `Rejection` (mismatch) |

item02 has stubs only for the stages before `match_gate`, because the pipeline stops there.

item01's `highlight.json` stub has status `skipped` (no highlighted splat), because the fixture has no splat file. The real stage (Gemini boxes, then lifting on the render backend) runs on items with a splat, e.g. `samples/<scan_id>`; `scripts/try_highlight.py` runs it alone on a finished run.

`match_gate.json` holds per-view Jev answers (`item_usable`, `same_category`, `same_product` for each of the 12 views), in the same format the live stage saves to `runs/<item>/match_gate_raw.json`. The aggregation, verdict and seller-facing reason are computed in code (`stages/match_gate.py`), and `scripts/replay_match_gate.py` re-applies thresholds to stubs and saved runs.
