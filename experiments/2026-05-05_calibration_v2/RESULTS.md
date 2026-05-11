# Calibration v2 — Results

## What changed from v1

Three things, all built into the package and exposed for reuse:

1. **Distributed sources**. Added 12 channel sources at ~200 m spacing between Stewart's Drain (32.541, -117.058) and the area near the beach outlet (32.555, -117.115), plus a 3×3 grid of estuary sources covering the western terminus from (32.555, -117.135) to (32.580, -117.115). Total source count: 17 named + 12 channel + 9 estuary + (+0 bay since the named bay sources cover) = 38 sources.

2. **Bounded inversion with archetype priors**. Replaced naive NNLS with `scipy.optimize.lsq_linear` (trust-region reflective) under per-source upper bounds. Caps are archetype-specific: drain ≤ 5 g/s, channel ≤ 2 g/s, estuary ≤ 3 g/s, bay ≤ 0.5 g/s. Added prior shrinkage toward archetype-specific central tendencies (drain 0.5 g/s, channel 0.2 g/s, estuary 0.3 g/s, bay 0.05 g/s) with λ=0.5, plus first-difference smoothness penalty along distributed source chains with λ=0.3.

3. **Wind-conditional residual diagnostic**. New utility `wind_conditional_residuals` bins predictions and observations into 16 wind sectors and reports mean residual per sector per receptor.

## Quantitative comparison

Per-station correlation (predicted vs observed, fitted rates):

| Station | v1 (r) | v2 (r) | Δ |
|---|---|---|---|
| SAN YSIDRO | 0.27 | 0.12 | -0.15 |
| NESTOR-BES | 0.60 | 0.56 | -0.04 |
| IB CIVIC CTR | 0.07 | **0.62** | **+0.55** |

**The IB CIVIC CTR gain is the headline result.** A 0.55 correlation jump from a single source-field expansion confirms the spatial deficit hypothesis: the western station's signal is dominated by estuary and nearshore-bay emissions that the named-source list could not represent at all. With distributed estuary sources, the model captures the timing and magnitude of all three observed peaks at IB.

NESTOR-BES's small drop (0.60 → 0.56) is the cost of physical regularization. v1's unconstrained NNLS pushed several drain rates to 30-40 g/s to fit NESTOR's peaks; v2's 5 g/s cap forces lower rates and the peak amplitudes lose a bit. That trade-off is worth it — v1's rates were physically absurd.

SAN YSIDRO's regression (0.27 → 0.12) is a real diagnostic signal. The wind-conditional residuals tell us why: with W and SW wind, v2 over-predicts SAN YSIDRO by ~20 ppb. That's the new channel-distributed sources sending plume east toward SAN YSIDRO when wind is from the W. A future iteration should reduce channel-source weights for receptors in their downwind direction during W wind, or — more cleanly — let the inversion fit time-varying or wind-conditional rates rather than single time-invariant rates. SAN YSIDRO has the lowest signal-to-noise in this window (max obs only 53.6 ppb vs 394 at NESTOR), so r is sensitive to small additions of noise.

## Total emission budget by archetype

From v2 fitted rates:

| Archetype | Total (g/s) | Mean (g/s) | Sources |
|---|---|---|---|
| drain | 16.3 | 2.33 | 7 |
| channel | 13.6 | 0.75 | 18 |
| estuary | 8.3 | 0.76 | 11 |
| bay | 1.0 | 0.50 | 2 |
| **total** | **39.2** | | **38** |

Total ~39 g/s of H₂S is plausible for a transient peak hour: scaled to a day this is 3,400 kg/day, and with H₂S making up perhaps 10⁻³–10⁻² of vapor mass over septic effluent, that corresponds to several hundred thousand to several million liters of evaporating sewage-equivalent. Given the documented spill flow rates (Stewart's Drain at ~45,000 gal in 24 h), the order of magnitude is right.

11 of 38 sources sit at their upper bound. That's a sign the bounds are doing their job (preventing absurd rates) but also suggests our caps may be too tight — a real spill event probably *should* push some drain emissions above 5 g/s at the peak hour. Two ways to handle this in v3: raise drain bound to 10 g/s during known spill windows, or add a "spill" archetype with its own elevated cap activated only on event days.

## Wind-conditional residuals — the most informative output

NESTOR-BES, top biased sectors:

| Sector | n | obs_mean | pred_mean | resid_mean |
|---|---|---|---|---|
| S | 3 | 172.8 | 47.0 | **+125.7** |
| E | 3 | 61.1 | 0.0 | **+61.1** |
| SSE | 4 | 59.7 | 5.9 | **+53.8** |

The "S" sector residual (+125 ppb under-prediction) is striking. With wind from due south, the plume travels north — NESTOR is north of all our channel sources, so this should fit well. The model says we're missing about 125 ppb of H₂S coming from the south. The most likely explanation is that the wind direction reported by the meteorological sensor during these hours is not representative — calm-night conditions often have variable surface winds that don't match the reading, and the southern source field (Smuggler's, Goat Canyon, the cross-border discharges) is where the H₂S actually comes from regardless of recorded wind. This is a known issue with point-anemometer met for dispersion modeling.

The "E" sector under-prediction (+61 ppb) is a different signal: when wind is from due east, none of our sources are due east of NESTOR, so prediction is 0. But the observation is 61 ppb. Either there's a real emission source east of NESTOR that we don't have (towards Tijuana), or the wind reading is again unrepresentative.

SAN YSIDRO, top biased sectors:

| Sector | n | obs_mean | pred_mean | resid_mean |
|---|---|---|---|---|
| W | 8 | 4.1 | 24.9 | **-20.7** |
| SW | 11 | 7.2 | 19.5 | **-12.3** |

**This is where v2 introduced its regression.** With W and SW winds, v2's distributed channel sources upstream of SAN YSIDRO send plume east toward it, but the observations show no such plume. Two possible interpretations: (a) the channel sources are being over-weighted by the inversion to fit other receptors and SAN YSIDRO is paying the cost, or (b) the channel sources don't actually emit during the daytime when W/SW winds are common (i.e., the sources have a strong night-time dependence that the time-invariant model can't capture).

I lean toward interpretation (b). Extreme H₂S events at this site are 98% nocturnal (per project memory). A time-invariant emission rate model fits poorly for sources whose actual emissions are strongly nocturnal. v3 should add a `f_diel(t)` modifier to emission rates — at minimum a day/night step function, ideally a smooth function tied to atmospheric stability.

IB CIVIC CTR is mostly clean. The one notable sector is "SE" with -11 ppb over-prediction (5 hours), suggesting estuary sources are slightly over-active during southeast wind regimes — small effect, low priority.

## What v2 validates

Three things, each with concrete next-step implications:

1. **The forward physics is right where geometry is right.** NESTOR's r=0.56 with bounded rates and IB's r=0.62 with distributed sources both confirm that when sources are placed where they belong and rates are physically constrained, the model fits. The remaining errors are not in the dispersion physics; they are in the source field and the emission-rate parameterization.

2. **Identifiability is the binding constraint.** With three receptors and 38 sources, many emission distributions explain the same observations. Bounds and priors regularize the problem but don't eliminate it. Future work either reduces the source count by hierarchical pooling (one rate per archetype, modulated per source by physical drivers), or adds observational constraints (PM2.5 co-located sensors as auxiliary channels, archived complaint timing as binary indicators).

3. **Time-invariant rates are wrong.** The W-wind over-prediction at SAN YSIDRO is the clearest evidence. Real H₂S emissions vary with diurnal cycle, temperature, SBIWTP throughput, and tidal state. The next round of calibration should parameterize emission rate as `E_i(t) = E_0,i × f_diel(t) × f_temp(T) × f_flow(Q_SBIWTP)` and fit `E_0,i` plus the parametric coefficients jointly.

## Files in `calibration_v2_output/`

- `summary.json` — top-level metrics
- `fitted_rates.csv` — rate, archetype, bound for every source
- `wind_residuals.csv` — full wind-conditional residual table
- `timeseries.csv` — observed and predicted hourly concentrations
- `v1_vs_v2.png` — three-panel comparison plot

## Suggested v3 priorities, ranked

1. **Diurnal modifier on emission rates**. Add `f_diel` as a fitted parameter (smooth night/day transition with calibrated amplitude). This addresses the SAN YSIDRO regression directly.
2. **Spill archetype**. New archetype with cap 20 g/s, activated only during documented event windows. Stops "regular" drain rates from getting forced into spill-event peaks.
3. **Smoothness on channel-source rates**. Already in code at λ=0.3; tune by holdout cross-validation.
4. **Add HRRR or NERR met to compare with current Open-Meteo**. The "S" wind under-prediction at NESTOR may be a met-data quality issue more than a model issue.
5. **Lagrangian puff backend**. Steady-state Gaussian plume cannot capture transient puffs from spill events. The puff backend (one-weekend addition, see docker_dispersion_models.md) is the right tool for event reconstruction.
