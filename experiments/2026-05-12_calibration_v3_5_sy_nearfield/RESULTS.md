# Results — calibration v3.5 (SY near-field arc)

**Run on:** 2026-05-12
**Runtime:** ~7 s
**Status:** ⚠️ **Hypothesis rejected, but clarifying.** Near-field
            point sources do *not* fix SAN YSIDRO. SY's weakness is a
            representativeness limit, not a missing point source. A
            small genuine NESTOR gain makes v3.5 the marginal best
            overall config.

## Headline (Apr 1-14 holdout, single-amp diel "v3" variant)

| Receptor      | Metric   | v3.2  | v3.5  | Δ      | Guard |
|---------------|----------|------:|------:|-------:|-------|
| SAN YSIDRO    | Spearman | 0.165 | 0.182 | +0.018 | target |
| NESTOR - BES  | Spearman | 0.498 | 0.525 | +0.028 | ✅ no regression |
| IB CIVIC CTR  | Spearman | 0.469 | 0.473 | +0.004 | ✅ no regression |
| SAN YSIDRO    | log-Pear | 0.210 | 0.237 | +0.027 | — |
| SAN YSIDRO    | Pearson  | 0.200 | 0.199 | −0.001 | — |

Overfitting guard **passes** (NESTOR/IB did not regress — they
slightly improved). But the SY Spearman gain is small (+0.018).

## Key finding — the near-field sources absorb almost nothing

SY near-field fitted rates (v3 single-amp diel):

| Source | Position rel. SY | Rate (g/s) |
|--------|------------------|-----------:|
| syWNW  | ~2.0 km WNW      | 0.099      |
| syNW   | ~2.2 km NW       | 0.071      |
| syS    | ~1.4 km S (border)| 0.013     |
| syE    | ~1.6 km E        | 0.008      |
| syW    | ~2.0 km W        | **0.000**  |
| **total sy_nearfield** | | **0.19**  |

For comparison the v3.2 **NE grid absorbed 2.48 g/s** under the same
fit, and the *whole* source field totals 12.5 g/s. NNLS is demonstrably
willing to attribute large rates to candidate sources when the data
supports them (it did exactly that for the NE grid in v3.2). It
declined to do so for the SY near-field arc — including `syW`, placed
directly in SY's single biggest uncovered wind regime (W/WNW, ~98
holdout hours at ~7 ppb), which fit to **exactly zero**.

**This is strong evidence against the missing-near-field-source
hypothesis.** If a coherent local / cross-border point source existed
within a few km of SY, the inversion would have found it.

## What this means

1. **SY's poor fit is qualitatively different from NESTOR's.** NESTOR's
   N-wind residual was a genuine missing source (the NE grid fixed it,
   Spearman 0.24 → 0.50 across the v3 line). SY's residual is **not**
   point-source-shaped. The persistent 2.5-7 ppb floor present across
   *all* wind directions cannot be produced by any single upwind point
   — it would require an omnidirectional/area term or is simply not
   resolvable by a 3-receptor Gaussian-plume model with shared met.

2. **SY is representativeness-limited.** It sits in a complex urban
   microenvironment at the border. The likely ceiling for SY under
   this modeling approach is ~0.18 Spearman. Candidate explanations,
   none fixable by adding point sources:
   - SY-microscale wind not captured (even SY-local met diverges from
     NESTOR only ~7% of hours, so this is partial at best)
   - genuine local urban / vehicular / cross-border *area* background
   - instrument baseline / siting effects
   - sub-grid dispersion the Gaussian plume can't resolve at ~1 km

3. **v3.5 is nonetheless the marginal best overall config** — NESTOR
   Spearman 0.498 → 0.525 is a real (if small) gain, and nothing
   regressed. The five SY candidates act as weak distributed
   absorbers that slightly sharpen the NESTOR-area fit. Keep them;
   they don't hurt.

4. **Stop trying to fix SY with more/closer sources.** Two source-
   addition experiments (v3.2 NE grid helped NESTOR not SY's ordering;
   v3.5 near-field arc helped neither) now point the same way.

## What should be done next

1. **Reframe the project's success claim around NESTOR.** NESTOR is the
   well-resolved receptor (Spearman 0.525, log-Pearson 0.49). SY and IB
   are met/representativeness-limited and should be reported as such,
   not treated as fixable by model tweaks.
2. **If SY matters for the application**, the lever is *data*, not
   model: a co-located SY anemometer + a local/area background term,
   or a higher-resolution met field. That's an instrumentation /
   data-acquisition ask, not a calibration experiment.
3. **Diminishing returns on the v3 line.** v3.5 is the best config;
   further point-source tinkering is unlikely to move the headline.
   The next high-value work is the service-repo PR to make Spearman +
   log-Pearson first-class in the reported diagnostics (currently
   Pearson-only), so future runs report the metric that matters.
4. Optionally: a sensitivity/Sobol run (experiments-repo issue #2,
   NRP) to formally rank which parameters the holdout fit is actually
   sensitive to — but that's blocked on NRP infra.

## Limitations / caveats

- **Single holdout window (Apr 1-14, n≈300/receptor).** SY's apparent
  ceiling could shift on a different window; the *qualitative*
  conclusion (NNLS won't fund near-SY sources) is robust because the
  contrast with the NE grid's 2.5 g/s is so large.
- **Near-field arc geometry is hand-placed.** A denser SY ring might
  find a cell that absorbs more, but the `syW`-fits-to-zero result in
  the most-uncovered direction makes that unlikely to change the story.
- **"Representativeness limit" is an inference, not a proof.** It's the
  best explanation given that two independent source-addition attempts
  failed to lift SY ordering while readily lifting NESTOR's.

## Files

- `output/summary.json` — all variants, now including Spearman +
  log-Pearson per receptor (headline metric per the reframe)
- `output/fitted_rates_v3.csv` — note the ~0 sy_nearfield rates
- `output/timeseries_*.csv`, `output/wind_residuals_*.csv`
