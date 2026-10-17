# Fixtures

One folder per test item:

```
itemNN/
  input.json       what the seller provides (seller_name, may be null)
  expected.json    the outcome the pipeline should reach
  stubs/<stage>.json
  views/           real renders go here (not yet captured)
  baseline.png     real baseline photo goes here (not yet captured)
```

**The `stubs/` data is hand-written placeholder data, not real model output.** Each stubbed stage loads `stubs/<stage>.json` instead of calling Gemini or Jev. Replace a stub with recorded real output once that stage is implemented. The prices are not real comps and have no source URL. The image paths point to files that don't exist yet.

| Item | Scenario | Expected |
|---|---|---|
| item01 | Used black Sony WH-1000XM4 with light wear, no seller name | `Listing` |
| item02 | Seller typed "Sony WH-1000XM4", but the scan is a Bose QuietComfort 45 | `Rejection` (mismatch) |

item02 has stubs only for the stages before `match_gate`, because the pipeline stops there.

`match_gate.json` holds only the two Jev scores. The verdict and the seller-facing reason are computed in code (`stages/match_gate.py`).
