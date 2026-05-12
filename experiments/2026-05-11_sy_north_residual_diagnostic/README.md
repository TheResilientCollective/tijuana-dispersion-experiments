# SAN YSIDRO N/NE residual — diagnostic (no fitting)

**Date:** 2026-05-11
**Status:** done
**Author:** autonomous (Claude Code session)
**Followup to:** [calibration_v3](../2026-05-11_calibration_v3/)

## Question

The v3 calibration's holdout (Apr 1-14, 2026) showed a large
un-modeled residual at SAN YSIDRO during N / NNE / NE / E winds — the
model predicts ≈ 0, observation is 6–30 ppb. Where does that residual
come from, and which fix should the next experiment pursue?

## Approach

Pure data analysis, no fitting:

1. Per-sector mean H₂S at all three receptors across the holdout
   window, using NESTOR's wind direction as the canonical met.
2. Hour-of-day distribution of "NESTOR > 50 ppb" episodes.
3. Cross-check: when SY is elevated under N/NE winds, what are
   NESTOR and IB CIVIC CTR showing at the same hour?
4. Inspection of v3's fitted rates — which sources hit their
   archetype upper bound?

All in `run.py`. Outputs to `output/` (gitignored).

## How to reproduce

```bash
cd experiments/2026-05-11_sy_north_residual_diagnostic
uv run python run.py
```

## Dependencies

- `tijuana-dispersion` at `v0.3.0`
- `../../data/modeldata_h2s_nofill.parquet` (fetched via `scripts/fetch_data.py`)
- `../2026-05-11_calibration_v3/output/fitted_rates_v3.csv` (the fitted
  rates we inspect for bound-hitting)

## Notes

This is a "no-fitting" experiment by design. The whole point is to
characterize the residual *before* committing to a parametric fix —
v3.1 had several plausible designs (per-archetype diel, relaxed bay
caps, added NE source), and choosing among them needs the
data-level evidence here.
