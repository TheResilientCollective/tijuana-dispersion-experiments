# Calibration Status Log

This is the running log of where the H₂S dispersion calibration stands. **Read this first** at the start of any session. Update it after every meaningful experiment.

Format for each entry:

```
## YYYY-MM-DD — <experiment short name>

**Question**: ...
**Result**: ...
**State change**: <what we now believe vs before>
**Next**: <what experiment this points toward>
```

Don't delete old entries. The log is the project's memory.

---

## 2026-05-11 — calibration_v3 (diurnal modifier)

**Question**: Does adding `f_diel(t)` on emission rates fix v2's
SAN YSIDRO W/SW over-prediction and the IB CIVIC CTR magnitude/timing
mismatch identified by the sensitivity LHS?

**Result**: Partial pass. v3 fits `diel_amplitude=1.75`, `phase=4:10 am`
on Feb 1 – Mar 31, 2026; holdout on Apr 1-14. SAN YSIDRO holdout r
improves from 0.041 (v2 refit) to 0.063 (v3); NESTOR-BES from 0.201
to 0.211; IB CIVIC CTR essentially unchanged (0.091 → 0.088). However,
the W/SW residual at SAN YSIDRO — the load-bearing acceptance criterion —
grew from +1.39 to +1.76 ppb (got *worse*). Importantly, v2's
originally-reported r=0.60/0.62 numbers were on the 72-hour Mar 13-15
spill window; refit on the full Feb-Mar window v2's r is 0.39/0.15 at
NESTOR/IB. The 2-month window is a much harder fit than v2 communicated.

**State change**:
- We now believe the diel modifier was the right shape of fix for the
  v2 Mar 13-15 diagnostic but not for the *dominant* residual seen on
  a broader holdout. The Apr 1-14 SAN YSIDRO residual is dominated by
  *northern* winds where the model has zero sources and predicts ~0
  while obs is 6-30 ppb. That points to a missing source east or NE of
  SAN YSIDRO (Otay Mesa industrial? cross-border emission? local
  background?), not a temporal-modulation problem.
- We now believe v2's Mar 13-15 metrics were upper-bounded by the spill
  event boosting signal. Going forward, calibration reports must include
  holdout window numbers by default.

**Next**:
1. Investigate the SAN YSIDRO N/NE residual: identify candidate sources,
   pull weather-station data colocated with SY to verify wind reading
   isn't the issue.
2. Per-archetype diel (drain/channel vs estuary) — currently a single
   global multiplier.
3. Expand outer optimization to include Q₁₀ and substrate params.
4. Add a "background" or "Otay Mesa" source east of SY and refit.

---

## 2026-05-05 — sensitivity_lhs

**Question**: Which emissions-model parameters most influence the fit?

**Result**: 200-sample Latin Hypercube across 11 emissions parameters, evaluated on the Mar 13-15 window using the Gaussian plume backend. `f_arch_estuary` is the dominant single sensitivity (Pearson r=-0.64 against NESTOR's correlation metric). Counter-intuitively, IB CIVIC CTR's *timing* fit prefers more drain weight and less estuary weight (r=+0.30 and r=-0.35 respectively) — opposite to v2's NNLS attribution. v2 fit IB's magnitude well via estuary weight, but at the cost of phase.

**State change**: We now believe v2's estuary-heavy attribution at IB is a magnitude-driven artifact of the time-invariant model, not a real geophysical signal. The diurnal modifier is the right fix because the W-wind over-prediction at SAN YSIDRO is the same artifact in mirror image. Both stations need temporally-varying source weights to fit timing and magnitude jointly.

**Next**: Implement a diurnal modifier on emission rates (v3). Re-run on Mar 13-15 to confirm IB attribution shifts toward drains as predicted.

---

## 2026-05-05 — calibration_v2

**Question**: Does adding distributed sources (12 channel + 9 estuary grid) plus archetype-bounded NNLS materially improve fit at IB CIVIC CTR?

**Result**: Yes. r=0.07 → r=0.62 at IB CIVIC CTR. NESTOR fit slightly worse (0.60→0.56) due to physical bounds preventing v1's 40 g/s phantom rates. SAN YSIDRO regressed (0.27→0.12) due to the time-invariant model overpredicting during W-wind regimes when channel sources should have been quiet (daytime). Wind-conditional residual diagnostic surfaced this as +20 ppb over-prediction at SAN YSIDRO with W and SW winds.

**State change**: Distributed estuary sources are a real geophysical feature, not a model artifact. Time-invariant emissions cannot fit IB and SAN YSIDRO simultaneously. Bounded NNLS works (no more phantom rates) but the bounds also reveal that 11/38 sources hit their upper limit — a signal that some baseline rates need event-conditional relaxation (e.g., a "spill" archetype with cap 20 g/s, active only during documented event windows).

**Next**: This pointed to the sensitivity analysis (above) and to the diurnal modifier as v3's core addition.

---

## 2026-05-05 — demo_v1 (baseline)

**Question**: Does the dispersion service pipeline work end-to-end on real data, with reasonable physics?

**Result**: Yes. Forward Gaussian plume + naive NNLS inversion ran in ~50 ms over a 72-hour window. NESTOR fit r=0.60. SAN YSIDRO r=0.27. IB CIVIC CTR r=0.07. Several sources received unconstrained fitted rates of 30-40 g/s — physically absurd, motivating archetype bounds in v2.

**State change**: The forward physics is correct (Gaussian plume rotation, σ coefficients, ground reflection). The NNLS inversion is also correct given its inputs. The problem is upstream: insufficient sources and unconstrained rates.

**Next**: v2 (above).

---

## Open questions (not yet experiments)

These are flagged for future investigation. Don't guess; design an experiment that resolves the question.

- **Mixing height**: the current plume code assumes unbounded vertical mixing. Under nocturnal stable conditions the actual mixing height collapses to ~50-200 m, which would amplify ground-level concentrations 5-10× from the same emissions. Possible explanation for why v2's fitted rates are 100× the literature priors. *Experiment to design*: integrate a mixing-height cap into `core.py` and re-fit Mar 13-15 with literature-default rates; see if fit improves.

- **Wind data quality during calm nights**: the wind-conditional residual table for NESTOR shows +125 ppb under-prediction during "S" wind hours. Three of those hours; with mean reported wind 1.5 m/s. Calm-night anemometer readings are notoriously unrepresentative because surface eddies dominate. *Experiment to design*: pull NERR (TJRTLMET) hourly winds for the same window and compare to Open-Meteo; if NERR shows different directions, the residual is met-error, not source attribution.

- **Substrate model parameterization**: the inverse-SBIWTP form `f_substrate = 1 + α × max(0, threshold - flow)` is a placeholder. The geodemic-repo emissions model has a more developed form. *Experiment to design*: port the geodemic substrate function into the bridge hook in `emissions.py`, calibrate the rest of the parameters with substrate held to that form, and compare.
