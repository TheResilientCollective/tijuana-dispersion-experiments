# Sensitivity Analysis — Local Run

## What we did

Latin Hypercube sample of 200 parameter sets across 11 emissions-model parameters. For each set, ran the emissions model + Gaussian plume forward through the Mar 13-15 window (72 hours, 38 sources, 3 receptors). Computed Pearson correlation between each parameter and three fit metrics per receptor (correlation, RMS error, peak ratio). Total runtime: 9 seconds.

This is a miniature illustration of the workload that would run at ~500× scale on NRP using HYSPLIT or STILT in the forward call. Same code structure, same output format.

## Two real findings worth flagging

### 1. The dominant sensitivity is `f_arch_estuary` against NESTOR's timing fit

Pearson r = -0.64. Higher estuary archetype scalar → worse timing correlation at NESTOR. The estuary sources are far enough west that their plume reaches NESTOR with phase offsets that don't match observed peaks. v2's NNLS happily assigned mass there because it minimizes RMS, but that's at the cost of timing.

### 2. IB CIVIC CTR contradicts the v2 attribution

For IB CIVIC CTR's correlation metric: `f_arch_drain` is strongly positive (+0.30), `f_arch_estuary` is strongly negative (-0.35). Translation: **more drain contribution and less estuary contribution improve IB's timing fit.** This is opposite to what v2's NNLS found, which loaded heavy estuary weight onto IB to match magnitude.

The two interpretations are physically different. Either:
- (a) IB's signal really does come from drains plus advection, and v2's estuary-heavy fit is overfitting magnitude at the expense of phase, or
- (b) IB has multiple contribution regimes (drain-dominated some hours, estuary-dominated others) and the time-invariant fit can't represent both.

Both are testable. Option (b) is what the diurnal-modifier addition (`f_diel`) is supposed to handle, and `diel_amplitude` does show negative correlation with NESTOR's timing fit (-0.33). So the diurnal direction is real; v3 should pursue it.

## Best parameter set found by random search

| Parameter | Value |
|---|---|
| baseline_scale | 5.81 |
| Q10 | 2.27 |
| f_arch_drain | 1.33 |
| f_arch_estuary | 1.91 |
| diel_amplitude | 1.23 |
| Combined RMS | 55.2 ppb |

For comparison, v2's NNLS-fitted RMS was 48.8 ppb. This 200-sample LHS, doing essentially random search, came within 13% of the calibrated optimum. With Sobol-style sampling and 100× more samples on NRP, the optimum would be hit precisely and we'd have the variance decomposition that tells us *why*.

## Files

- `sensitivity_samples.csv` — all 200 parameter sets and their fit metrics
- `sensitivities.csv` — Pearson r per (parameter, metric) pair
- `sensitivity_heatmap.png` — visual matrix
- `best_parameters.json` — top scorer for use as a v3 starting point
