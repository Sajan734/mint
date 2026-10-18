# PREREG: buyer-agent evaluation (v2)
Frozen before the first PASLCD run. Approved by: <user>, <date>. results.md quotes this file's commit.

## Version history
v2: the verdict is strictly binary (same / different). Replaced `same` (0.25) with `match_min`
(0.70): same iff match_score = 1 - strongest category evidence >= 0.70. The 0.70 was chosen from
mismatch and synthetic data only; there is no real true-match data yet. If real matches get
rejected, loosen it to 0.60 and make a new version (v3).
v1 (superseded): sha256 37d9ed4f3fcf050453430871d00961eafbc45b7a4bd0029373665a3288bd3187.

## Frozen thresholds
thresholds_sha256: cc1fc424ac6470f227b85c91762dfbb33f81d3aaee6a82ef4b0ad106e3e3a8ba
```json thresholds
{
  "ambiguity_max": 0.85,
  "different": 0.5,
  "match_min": 0.7,
  "min_answered": 8,
  "min_views": 6,
  "quality_frac": 0.75,
  "quality_min": 0.5,
  "same_usable_frac": 0.75,
  "support": 2,
  "viewpoint_min": 0.5
}
```

## Split
Tune: Printing_area, Porch. Held-out: Pots, Zen. Held-out runs only after this file is committed.
A threshold change creates a new version of this file, re-runs tune, and labels all later results "tuned on tune split".

## Strata cut-offs (changed cases)
small < 2% mask area, medium 2-10%, large > 10%. Merges: <filled by U30 log>.

## Pre-registered cases
```json cases
[]
```

## Pass rule (stated before running)
Wrong = changed/different case -> same, or same case -> different. S2 passes only with zero wrong in all 3 runs.
Report n, Wilson 95% intervals, false-same rate on changed, run spread. No accuracy claim.

## Eye-check log (pair validity only, never labels)
<case>: <what was checked>, <by>, <date>
