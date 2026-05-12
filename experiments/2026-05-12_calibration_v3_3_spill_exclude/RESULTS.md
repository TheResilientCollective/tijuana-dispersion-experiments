# Results — calibration v3.3 (spill exclusion)

**Run on:** 2026-05-12
**Runtime:** ~8 s
**Status:** ❌ **Negative result.** Spill exclusion *hurts* holdout fit
            across all three variants. Hypothesis rejected.

## Question

Does excluding the documented Mar 13-15 spill from training give
lower / more plausible source rates and better holdout
generalisation?

## Numbers

### Holdout (Apr 1-14) per-receptor r — v3.3 vs v3.2

| Variant         | v3.2 (incl spill) | v3.3 (excl spill) | Δ      |
|-----------------|------------------:|------------------:|-------:|
| v2 SAN YSIDRO   | 0.180             | 0.181             | +0.001 |
| v3 SAN YSIDRO   | **0.200**         | 0.198             | −0.002 |
| v3.1 SAN YSIDRO | 0.194             | 0.183             | −0.011 |
| v2 NESTOR-BES   | 0.236             | 0.205             | **−0.031** |
| v3 NESTOR-BES   | **0.242**         | 0.218             | **−0.024** |
| v3.1 NESTOR-BES | 0.233             | 0.190             | **−0.043** |
| v2 IB CIVIC CTR | 0.082             | 0.074             | −0.008 |
| v3 IB CIVIC CTR | 0.087             | 0.082             | −0.005 |
| v3.1 IB CIVIC CTR | 0.086           | 0.078             | −0.008 |

SAN YSIDRO is essentially unchanged. **NESTOR-BES regresses by 0.02 to 0.04**
across all variants. IB drops slightly. No variant improves.

Note: train metrics paradoxically *improve* (v3 SY train 0.315 → 0.346;
v3 NESTOR train 0.402 → 0.429) — the model fits the cleaner non-spill
training data more easily, but that fit doesn't transfer.

### Where did the spill's mass go? (v3 single-amp diel, by archetype, train fit)

| Archetype | v3.2 (incl) | v3.3 (excl) | Δ            |
|-----------|------------:|------------:|-------------:|
| drain     | 4.08        | 4.07        | −0.01 (≈ 0)  |
| channel   | 3.02        | **1.81**    | **−1.21 (−40%)** |
| northeast | 2.34        | 1.95        | −0.39        |
| estuary   | 1.41        | 1.37        | −0.04        |
| bay       | 0.76        | 0.67        | −0.10        |

**The biggest single change is channel sources: 3.0 → 1.8 g/s (−40%).**
Drain rates barely moved. Stewart's Drain stayed at 0.05-0.07 g/s in
both fits — it never absorbed the spill peak.

### Where did the spill's mass go *not* go?

Specifically Stewart's Drain (the documented spill source) had a
fitted rate of 0.07 g/s in v3.2 and 0.05 g/s in v3.3 — both
*decimals* of a g/s while the literature prior for drains is 0.5 g/s.
NNLS evidently never thought Stewart's was responsible for the
NESTOR peak during the spill. Instead, the upstream channel sources
(which had a slightly more favourable wind-direction geometry during
the peak hours) absorbed the signal.

## What this means

Three concrete updates:

1. **The hypothesis "spill inflates drain rates" was wrong.** Drain
   rates are stable across spill-in vs spill-out. The spill's signal
   was absorbed by channel sources, not drains.
2. **The Mar 13-15 spill carries useful signal for non-spill
   nocturnal regimes.** Excluding it costs holdout fit. The wind
   direction / source geometry that the model learned from the spill
   peak transfers to other nocturnal events.
3. **The "spill archetype" idea (cap 20 g/s, event-windowed
   activation) loses its main motivation.** If NNLS doesn't even
   attribute the spill to its actual source (Stewart's Drain), a
   spill-specific archetype isn't pulling the right lever.

## What should be done next

Stop chasing spill-exclusion. Higher-leverage:

1. **Investigate why channel sources absorb the spill instead of
   Stewart's Drain.** Either wind direction during the spill hours
   was inconsistent with Stewart's→NESTOR bearing, or the channel
   sources happened to be geometrically better placed. Look at
   per-hour residuals for Stewart's Drain during the spill window.
2. **IB CIVIC CTR diagnostic** — the receptor stuck at holdout r ~ 0.08
   regardless of variant.
3. **Refined NE grid in the v3.2 hot zone** around (32.575, -117.040).
4. **The channel sources running hot is a flag.** 12 channel
   sources × ~0.15-0.7 g/s each is implausible — these are bridges
   and crossings, not point sources. They're absorbing other things
   the model can't explain. Worth reducing the channel-source count
   or constraining their bounds tighter.

## Limitations / caveats

- **Only one spill event tried.** Other documented spills might give
  different results. The Mar 13-15 event may be unrepresentative.
- **Met series treated as ground truth.** If wind direction during
  the spill hours was actually different from the NESTOR reading,
  source-attribution would be off — but that error is shared between
  v3.2 and v3.3 so it doesn't explain the differential.
- **Quick reproduction:** for the next session, just compare v3.2 and
  v3.3 summary.json files; no need to refit.

## Files

- `output/summary.json` — metrics for all three variants, with
  `spill_excluded_hours: 60` flag
- `output/fitted_rates_*.csv`, `output/timeseries_*.csv`,
  `output/wind_residuals_*.csv`
