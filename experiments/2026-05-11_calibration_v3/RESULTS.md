# Results — calibration v3 (diurnal modifier on emissions)

**Run on:** 2026-05-11
**Runtime:** ~5 s (full fit + holdout eval)
**Outputs:** `output/summary.json`, `output/timeseries_*.csv`,
            `output/wind_residuals_*.csv`, `output/fitted_rates_*.csv` (gitignored)
**v2 baseline:** refit on the same windows (no diel modifier) for fair comparison
**Status:** ⚠️ **Partial pass.** Criterion #1 met by a small margin. Criterion
            #2 (the load-bearing one) failed — v3 does **not** reduce the
            W/SW over-prediction at SAN YSIDRO. The Apr holdout is dominated
            by a different failure mode that the diel modifier cannot fix.

## Question

Does adding a diurnal modifier `f_diel(t)` on emission rates fix the v2
diagnostic failures at SAN YSIDRO (W/SW daytime over-prediction) and
IB CIVIC CTR (NNLS magnitude/timing mismatch)?

## What we did

- Refit the v2 source field (17 named + 12 channel + 9 estuary grid =
  38 sources) on a Feb 1 – Mar 31, 2026 training window. v2 was originally
  reported on Mar 13–15 only; this is the first time v2 metrics on the
  broader window have been computed.
- Held out Apr 1 – Apr 14, 2026 (312 hours per station, 919 valid obs).
- v3 added a smooth-cosine diel modifier `d(t) = 1 + ½(amplitude−1)(1 + cos(2π(h−phase)/24))`
  multiplied into each source's emission rate per hour, then solved the
  same bounded NNLS (trust-region reflective, archetype caps + ridge to
  archetype priors) for per-source baselines. Outer Nelder-Mead searched
  `(diel_amplitude, diel_phase_hours)` minimizing log-MSE on receptor
  concentrations.
- 22 outer evaluations, ~5 s total wall time on a M-series MacBook.

## Key findings

1. **v3's diel parameters converge sensibly.** `diel_amplitude = 1.75`
   (1.0 = no modifier, 2.0 = 2× nocturnal vs daytime) and
   `phase_hours = 4.17` (4:10 am peak). Both match the prior that H₂S
   extreme events are nocturnal.

2. **v3 marginally improves SAN YSIDRO holdout fit.** r climbs from
   0.041 (v2) to 0.063 (v3) — a real but small directional improvement.

3. **The W/SW residual at SAN YSIDRO does *not* shrink.** This was the
   primary motivation for v3 from the v2 diagnostic, but
   weighted-mean residual in W/SW/WSW sectors grew from +1.39 ppb (v2)
   to +1.76 ppb (v3). On the Apr holdout, the SAN YSIDRO residual is
   *dominated* by *northern* sectors where the model predicts ~0 and
   obs is 6–30 ppb — a problem the diel modifier cannot address.

4. **NESTOR-BES and IB CIVIC CTR holdout fit essentially unchanged.**
   NESTOR: 0.201 → 0.211 (negligible). IB: 0.091 → 0.088 (within noise).

5. **The v2-era "great" Mar 13-15 numbers don't generalize.** v2 was
   originally reported with r=0.60 (NESTOR), 0.62 (IB CIVIC CTR), 0.12
   (SAN YSIDRO) on Mar 13-15. Refit on the broader Feb-Mar window we get
   0.39, 0.15, 0.27 respectively. The Mar 13-15 figures reflected a
   period of strong spill-event signal where physics fits well; over a
   typical 2-month window with mixed baseline + episodic regimes the
   fit is substantially weaker.

## Numbers

### Per-receptor metrics (train: Feb 1 – Mar 31; holdout: Apr 1 – Apr 14)

| Window  | Receptor      | metric  | v2     | v3     | Δ      |
|---------|---------------|---------|--------|--------|--------|
| train   | SAN YSIDRO    | r       | 0.266  | 0.313  | +0.047 |
| train   | NESTOR - BES  | r       | 0.386  | 0.398  | +0.012 |
| train   | IB CIVIC CTR  | r       | 0.146  | 0.164  | +0.018 |
| holdout | SAN YSIDRO    | r       | 0.041  | 0.063  | +0.022 |
| holdout | NESTOR - BES  | r       | 0.201  | 0.211  | +0.010 |
| holdout | IB CIVIC CTR  | r       | 0.091  | 0.088  | −0.003 |
| holdout | SAN YSIDRO    | RMS ppb | 13.35  | 13.36  |  0.00  |
| holdout | NESTOR - BES  | RMS ppb | 84.56  | 84.42  | −0.14  |
| holdout | IB CIVIC CTR  | RMS ppb | 25.22  | 28.04  | +2.82  |

### SAN YSIDRO wind-sector residuals on holdout (mean obs − mean pred, ppb; n_hours in parens)

| Sector | v2 resid | v3 resid | n  | Notes                              |
|--------|----------|----------|----|------------------------------------|
| N      | +30.3    | +30.3    | 9  | Model predicts 0; obs 30 ppb       |
| NNE    | +10.0    | +10.0    | 7  | Model predicts 0                   |
| NE     | +7.6     | +7.6     | 13 | Model predicts 0                   |
| ENE    | +6.2     | +6.2     | 13 | Model predicts 0                   |
| E      | +6.0     | +6.0     | 14 | Model predicts 0                   |
| SE     | +4.5     | +4.5     | 20 | Model predicts ~0                  |
| SW     | +1.9     | +2.3     | 18 | v3 *worse*                         |
| WSW    | +2.5     | +2.9     | 38 | v3 *worse*                         |
| W      | +0.5     | +0.8     | 60 | v3 slightly worse                  |
| WNW    | +5.8     | +5.9     | 39 | Comparable                         |
| NW     | +15.0    | +15.0    | 9  | Model predicts ~0                  |
| NNW    | +29.3    | +29.3    | 7  | Model predicts 0                   |

### Acceptance criteria

| # | Criterion                                                              | Result | Detail                          |
|---|------------------------------------------------------------------------|--------|---------------------------------|
| 1 | SAN YSIDRO holdout r > v2's                                            | ✅ pass | 0.063 > 0.041                  |
| 2 | W/SW residual at SAN YSIDRO reduced by ≥ 50%                            | ❌ fail | Increased 27% (+1.39 → +1.76 ppb) |
| 3 | NESTOR-BES holdout r not worse than v2 by > 0.05                       | ✅ pass | Δ = +0.010                     |
| 4 | RESULTS.md reports per-receptor r, RMS, wind-conditional residuals      | ✅ pass | (this file)                    |
| 5 | docs/calibration_status.md updated                                     | ✅ pass | (added 2026-05-11 entry)       |

**Overall: partial pass.** Criterion #2 fails — and it's the load-bearing one that
v3 was designed to address.

### v3 fitted diel parameters

- `diel_amplitude` = 1.75 (interior of bounds [1.0, 3.5])
- `diel_phase_hours` = 4.17 (peak at 4:10 am, interior of [0, 24])
- Outer optimization converged in 22 Nelder-Mead evaluations.

## What this means

The diel modifier was the right *shape* of fix for the v2-era diagnostic,
but the broader holdout window reveals the v2 diagnostic was a partial
view. The dominant residual at SAN YSIDRO on Apr 1-14 isn't a
daytime/W-wind over-prediction (which was small to start with — under
2 ppb mean). It's a much larger *under-prediction* during *northerly*
winds (model predicts ~0; obs is 6-30 ppb).

That under-prediction has a specific physical explanation: SAN YSIDRO
is on the east edge of the model domain. Sources are all to its *west*
(channel/estuary in the river valley). With wind from the north or
northeast, the model has nothing upwind of SAN YSIDRO and predicts
zero. But H₂S obs at SAN YSIDRO is 6-30 ppb in those sectors, meaning
**there's a source east or north of SAN YSIDRO we haven't included.**

Candidates worth investigating:
- Otay Mesa industrial / cross-border emissions
- A Tijuana-side source NE of the receptor
- Local agricultural / urban background that's not site-specific

The diurnal-modifier hypothesis is partially confirmed (better train
fit, better SAN YSIDRO holdout r) but it's clearly not the dominant
piece of the holdout error budget.

## What should be done next

In rough priority order:

1. **Investigate northerly residuals at SAN YSIDRO (highest value).** Look
   at the 36 hours where wind is N/NNE/NE/ENE/E and obs > 10 ppb at SY.
   Are these correlated with known events? Is the wind reading from
   NESTOR (the met source) consistent with SY-local wind?

2. **Re-evaluate v2 reporting honesty.** v2's "great" r=0.60-0.62 numbers
   were on a 72-hour spill-event window. The actual broader fit is r ≈
   0.15-0.39. This is a project-communication issue: future calibration
   reports should include holdout metrics by default.

3. **Per-archetype diel modifier (not a global one).** Estuary and
   channel/drain sources likely have different diurnal patterns
   (estuary peaks with dawn tidal mixing; channel may peak with
   nocturnal cooling). The current global-modifier formulation may be
   averaging them out.

4. **Add a Q₁₀/temperature term to the outer optimization.** Currently
   fixed at literature default. Free fitting might absorb some of the
   residual diurnal/seasonal structure.

5. **Add the Otay Mesa / cross-border source archetype** to the source
   field and re-fit. This addresses key finding 5 directly.

## Limitations / caveats

- **The Mar 13-15 v2 spill event is in the training window.** This
  inflates several drain rates and shifts the implicit diel phase. A
  pre-screening to exclude documented spill hours from training (or to
  fit a "spill" archetype that's only active in those hours) is the
  next obvious refinement.
- **Met series is NESTOR-only.** Wind at the 3 receptors is treated as
  identical to NESTOR's reading. The W/SW issue at SAN YSIDRO could
  partly be that the *local* SY wind differs from NESTOR's during
  certain regimes.
- **Outer optimization is 2-dimensional.** Adding Q₁₀, T_ref,
  substrate_α, substrate_threshold as outer variables (as the design doc
  envisaged) would let the system trade between diel and temperature
  modulation. Left for v3.1.
- **`cloud_cover` rescaled assumes percentage in [0, 100]** based on
  manifest spot-check; sample max is 100. If a future data refresh uses
  fractions (0-1) the diel-conditional Pasquill class will shift. Worth
  a defensive check in `tijuana_dispersion.core.pasquill_stability`.

## Files

- `output/summary.json` — per-receptor metrics + acceptance flags + diel params (machine-readable)
- `output/timeseries_train.csv` — hourly obs + v2 pred + v3 pred per receptor
- `output/timeseries_holdout.csv` — same on Apr 1-14
- `output/wind_residuals_v2.csv`, `wind_residuals_v3.csv` — per-sector residuals at each receptor
- `output/fitted_rates_v2.csv`, `fitted_rates_v3.csv` — per-source baseline rates
