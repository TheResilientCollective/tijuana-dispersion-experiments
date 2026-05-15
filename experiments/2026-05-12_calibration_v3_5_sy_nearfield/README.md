# calibration v3.5 — SAN YSIDRO near-field candidate arc

**Date:** 2026-05-12
**Status:** done
**Author:** autonomous (Claude Code session)
**Followup to:** ib_metric_reframe (SY identified as the real problem receptor)

## Question

The metric reframe showed SAN YSIDRO is the project's weakest receptor
under Spearman (~0.16 vs IB/NESTOR ~0.47-0.50). The SY ordering
diagnostic found the model under-predicts SY ~3× everywhere, has zero
spike skill, and predicts ≈0 in 27% of holdout hours where SY observes
a 2.5-7 ppb floor — with the biggest uncovered regime being W/WNW wind
(nearest modeled source 6.3 km away). SY is ~1.2 km from the
US-Mexico border with Tijuana urban/industrial immediately south.

**Hypothesis:** there is a near-field source (local urban /
cross-border) within ~1.5-3 km of SY that the river-valley source
field fundamentally lacks. Adding a candidate arc W→N→E→S of SY
should let NNLS absorb that rate and lift SY's rank-order fit.

## Approach

v3.2 source field (12-cell NE grid + relaxed bay cap) **plus** a
5-source near-field arc around SY, all ≥ 1.4 km from the receptor
(overfitting guard — a source parked on the receptor would "cheat").
Single-amp diel (canonical form; per-archetype retired after v3.1/v3.2).
Reports Spearman (headline per the metric reframe), log-Pearson, and
Pearson.

**Success criteria:**
- SY Spearman up vs v3.2's 0.165, AND
- NESTOR / IB Spearman do not regress by > 0.03 (a near-SY source must
  not help the other receptors; if it does, it's absorbing systematic
  error rather than representing a real SY source).

## Result preview

Hypothesis largely **rejected** — see RESULTS.md. The near-field
sources absorb almost no rate (0.19 g/s total vs the NE grid's 2.5).
SY's weakness is a representativeness limit, not a missing point
source. NESTOR sees a small genuine gain (0.498 → 0.525 Spearman),
making v3.5 the marginal best overall config.

## How to reproduce

```bash
uv sync --extra dev --extra service
python scripts/fetch_data.py --only modeldata_h2s_nofill
cd experiments/2026-05-12_calibration_v3_5_sy_nearfield
uv run python run.py
```

## Dependencies

- `tijuana-dispersion` at `v0.3.0`; `../../data/modeldata_h2s_nofill.parquet`
