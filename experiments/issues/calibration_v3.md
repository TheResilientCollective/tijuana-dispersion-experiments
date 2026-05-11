# v3 calibration: diurnal modifier emission parameterization

## Why

Calibration v2 (2026-05-05) revealed two diagnostic problems that point to the same root cause:

1. SAN YSIDRO regression: r dropped from 0.27 (v1) to 0.12 (v2) when distributed channel sources were added. Wind-conditional residuals show ~20 ppb over-prediction during W and SW winds. The new channel sources send plume east toward SAN YSIDRO when wind is from W, but observations show no such plume.

2. Sensitivity analysis (2026-05-05): `f_arch_estuary` is the dominant parameter with Pearson r=-0.64 against NESTOR's timing fit. For IB CIVIC CTR, lower estuary weight gives *better* timing correlation — opposite to v2's NNLS attribution.

Both findings point to the same explanation: emissions are not time-invariant. H₂S extreme events are 98% nocturnal at this site. A time-invariant emission rate model fits the average but misses the diurnal pattern; the inversion compensates by pushing mass to whichever sources happen to align with the observed peaks, even when that's spatially wrong.

The fix is a diurnal modifier `f_diel(t)` in the emissions parameterization.

## Scope

Implement and calibrate a diurnal modifier. Compare v2 vs v3 on the Mar 13-15 window, then validate on Apr 1-14 holdout.

1. Use the existing `f_diel(driver, params)` in `tijuana_emissions/functions.py` (smooth cosine, parameters `diel_amplitude` and `diel_phase_hours`).
2. Build a calibration loop that fits the parameter set: per-source baselines `E₀_i`, archetype scalars `f_arch`, plus the parametric coefficients (Q₁₀, T_ref, substrate_α, substrate_threshold, diel_amplitude, diel_phase_hours).
3. Use scipy.optimize.minimize with bounds; objective is weighted log-MSE on receptor concentrations.
4. Run on Feb 1 - Mar 31, 2026.
5. Evaluate on Apr 1-14 holdout.
6. Compare to v2 with the same metrics: per-receptor correlation, RMS, peak ratio, wind-conditional residuals.

## Acceptance criteria

- [ ] Experiment lives in `experiments/2026-MM-DD_calibration_v3/`.
- [ ] `RESULTS.md` reports per-receptor correlation, RMS, and wind-conditional residuals on the holdout window.
- [ ] **Required improvement:** SAN YSIDRO correlation on holdout > v2's holdout SAN YSIDRO. (We don't have v2 holdout numbers yet — establish them as a side task.)
- [ ] **Required improvement:** wind-conditional W/SW residual at SAN YSIDRO is reduced by at least 50%.
- [ ] No regression: NESTOR-BES correlation must not drop below v2's by more than 0.05.
- [ ] `CALIBRATION_LOG.md` updated.

## Things to figure out

- Whether the diurnal modifier is per-archetype (drains diurnal but estuary not) or global. My prior is per-archetype but with shared phase; sensitivity analysis can answer this in a follow-up.
- Whether to also add `f_temp` as a fitted parameter or pin Q₁₀ at the literature default. Easier to fit fewer parameters, but if the Q₁₀ prior is wrong it'll dominate residuals.
- Spill event handling: Mar 14-15 includes a documented Stewart's Drain spill. May need a separate "spill" archetype with elevated cap, activated only during the documented window. Otherwise the regular drain rate gets pushed up to fit the spill peak.

## Estimated effort

Two to three days, assuming the puff backend is not yet in. With puff in, add another day to integrate it into the ensemble.
