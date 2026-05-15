# IB CIVIC CTR diagnostic → metric reframe

**Date:** 2026-05-12
**Status:** done
**Author:** autonomous (Claude Code session)
**Followup to:** v3.2 / v3.3 (IB stuck at holdout Pearson r ≈ 0.087)

## Question

IB CIVIC CTR's holdout Pearson r sat at ~0.087 across every v3.x
variant — apparently un-improvable. Is the model actually failing on
IB, or is the metric misleading?

## What the diagnostic found (no fitting required)

1. **IB has no independent wind reading.** In
   `modeldata_h2s_nofill.parquet`, IB's `wind_direction_10m` and
   `wind_speed_10m` are *byte-identical* to NESTOR's (corr = 1.000,
   identical-fraction = 1.000). SAN YSIDRO, by contrast, has its own
   wind (identical-fraction vs NESTOR = 0.01). So every model that
   predicts IB is fundamentally limited to NESTOR-proxy met. This is a
   data limitation, not a model bug.

2. **IB is extremely heavy-tailed.** Holdout median = 0.5 ppb, mean =
   6.5 ppb, max = 130 ppb. The **top 3 hours carry 40% of the
   sum-of-squares**. Pearson r on such a series is determined by
   whether ~3 spike hours align — it is not a meaningful goodness
   measure here.

3. **Under rank / log metrics the model is fine.** For the v3
   (single-amp diel) fit on the Apr holdout:

   | Receptor      | Pearson | Spearman | log-Pearson |
   |---------------|--------:|---------:|------------:|
   | IB CIVIC CTR  | 0.087   | **0.469**| **0.446**   |
   | NESTOR - BES  | 0.242   | 0.498    | 0.499       |
   | SAN YSIDRO    | 0.200   | 0.165    | 0.226       |

   IB's Spearman (0.47) is close to NESTOR's (0.50). The model captures
   IB's *ordering* about as well as NESTOR's — the "IB problem" was a
   Pearson artifact.

4. **IB leads NESTOR by ~1 hour** (`corr(IB(t), NESTOR(t+1))` exceeds
   lag-0 for both Pearson and Spearman). With no IB-local wind we can't
   correct this; flagged as a known limitation.

5. **Note on SAN YSIDRO:** the *opposite* — its Pearson (0.20) is
   higher than its Spearman (0.17). For SY, Pearson is flattering. The
   metric choice matters per-receptor.

## Approach of this experiment

No new fitting. Recompute the entire v3.x family's holdout metrics
(v2 / v3 / v3.1, for v3.0 v3.1 v3.2 v3.3 runs) under three metrics —
Pearson, Spearman, log-Pearson — from the already-committed
`timeseries_holdout.csv` files. Produce a single comparison table so
the project can decide on a primary metric.

## How to reproduce

```bash
cd experiments/2026-05-12_ib_metric_reframe
uv run python run.py     # reads ../*/output/timeseries_holdout.csv ; no refit
```

## Dependencies

- Only `pandas`, `numpy`, `scipy` (no `tijuana-dispersion` — pure
  post-processing of prior runs' outputs).
- Reads `../2026-05-11_calibration_v3/output/timeseries_holdout.csv`
  and the v3.1 / v3.2 / v3.3 equivalents.

## Notes

This experiment changes how the project should *report* results, not
the model. The recommendation (see RESULTS.md) is to make Spearman the
headline metric for episodic H₂S fits and treat Pearson as secondary.
