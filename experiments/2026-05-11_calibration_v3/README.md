# calibration v3 — diurnal modifier on emissions

**Date:** 2026-05-11
**Status:** running
**Author:** automated bootstrap (Claude Code) — to be reviewed by @valentinedwv

## Question

Does adding a diurnal modifier `f_diel(t)` on emission rates fix the two
diagnostic failures left over from v2?

1. **SAN YSIDRO regression** — v1→v2 dropped r from 0.27 to 0.12 because
   the new distributed channel sources advect plume east during W/SW
   winds (typically daytime), but observations show no daytime plume
   there. A time-invariant model can't suppress channel emissions during
   the day.
2. **IB CIVIC CTR magnitude/timing mismatch** — v2's NNLS attributed
   IB's mass mostly to estuary, but the 2026-05-05 LHS sensitivity
   analysis found IB's *timing* fit prefers more drain weight. A model
   without time variation has to pick: it picks magnitude (estuary) and
   loses timing.

The unifying hypothesis: emissions are not time-invariant. H₂S extreme
events at this site are 98% nocturnal. A diel modifier should let the
inversion put the right *spatial* mass at the right *temporal* phase.

## Approach

1. **Window:** Feb 1 – Mar 31, 2026 train; Apr 1 – Apr 14 holdout.
2. **Establish v2 baseline on the same windows** (the design doc flags
   that v2 holdout numbers don't exist yet; this experiment computes
   them as a side product for fair comparison).
3. **Run v2 logic with `f_diel` enabled and fit the diel parameters
   (`diel_amplitude`, `diel_phase_hours`) jointly with per-source
   baselines and archetype scalars.**
   - Outer loop: `scipy.optimize.minimize` over parametric coefficients
     (Q₁₀, T_ref, substrate_α, substrate_threshold, `diel_amplitude`,
     `diel_phase_hours`).
   - Inner loop: bounded NNLS for per-source baselines, given the outer
     parameter set.
   - Objective: weighted log-MSE on receptor concentrations across all
     three sites with the train window.
4. **Evaluate** on holdout. Compare per-receptor:
   - Pearson correlation (timing fit)
   - RMS error (magnitude fit)
   - Wind-conditional residuals at SAN YSIDRO (the v2 diagnostic that
     surfaced the W/SW over-prediction)

## How to reproduce

```bash
# from the repo root
uv sync --all-extras            # or `--extra service` to include the service pin
python scripts/fetch_data.py --only modeldata_h2s_nofill
cd experiments/2026-05-11_calibration_v3
uv run python run.py            # full Feb-Mar fit + Apr holdout eval
uv run python run.py --quick    # fast smoke run on Mar 13-15 only
```

Inputs are pinned in `config.yaml`. Outputs land in `output/` (gitignored).
Result summary in `RESULTS.md` after the run completes.

## Acceptance criteria (from issue #1 + `experiments/issues/calibration_v3.md`)

- [ ] SAN YSIDRO correlation on holdout > v2's holdout SAN YSIDRO.
- [ ] Wind-conditional W/SW residual at SAN YSIDRO reduced by ≥50% vs v2.
- [ ] NESTOR-BES correlation no worse than v2 by more than 0.05.
- [ ] `RESULTS.md` reports per-receptor correlation, RMS, and
      wind-conditional residuals on the holdout window.
- [ ] `docs/calibration_status.md` updated with the result regardless
      of outcome.

## Dependencies

- `tijuana-dispersion` at tag `v0.3.0` (`f_diel` lives in
  `tijuana_dispersion.emissions`).
- `data/modeldata_h2s_nofill.parquet` — H₂S obs + meteorology, fetched via
  `scripts/fetch_data.py`. Date range covers Feb 2026 – present.

## Notes

The Mar 13–15 window includes a documented Stewart's Drain spill event
(peak observed 394 ppb). v2's design doc flags this as a possible source
of fitting artifacts and suggests either (a) leaving it in the training
window and accepting the inflated drain rate, or (b) splitting out a
"spill" archetype with an event-windowed activation. This experiment
uses option (a) — the holdout window (Apr 1–14) has no documented spill
events, so the holdout metrics are not contaminated by spill-specific
parameter inflation.
