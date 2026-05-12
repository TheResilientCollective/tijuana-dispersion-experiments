# Results — calibration v3.2

**Run on:** 2026-05-12
**Runtime:** ~12 s
**Status:** ✅ **Clear win.** Grid sweep nearly *doubles* SAN YSIDRO
            holdout r over v3.1, and a coherent spatial hot-spot
            emerges.

## Question

Does spreading 12 candidate sources across the Otay Mesa / cross-border
area (vs. v3.1's 2 fixed candidates) reveal a coherent source location?

## Key findings

### Headline numbers (Apr 1-14 holdout)

| Receptor      | v3 (orig) | v3.1 (2 candidates) | **v3.2 v2-style** | **v3.2 v3 (single-amp)** | v3.2 v3.1 (per-arch) |
|---------------|----------:|--------------------:|------------------:|-------------------------:|---------------------:|
| SAN YSIDRO    | 0.041     | 0.115              | **0.180**         | **0.200**                | 0.194                |
| NESTOR - BES  | 0.211     | 0.209              | 0.236             | **0.242**                | 0.233                |
| IB CIVIC CTR  | 0.086     | 0.087              | 0.082             | 0.087                    | 0.086                |

- **SAN YSIDRO holdout r jumps from 0.115 to 0.200** — almost double.
  Cumulative from the original v3 (no NE sources): **0.041 → 0.200**, a
  5× improvement.
- **NESTOR-BES also climbs from 0.21 to 0.24** — the grid lets bay-
  adjacent NE candidates absorb additional N-wind plume.
- **IB CIVIC CTR remains stuck at ~0.087.** The geometry: IB is west;
  NE candidates contribute nothing to IB at typical wind regimes.
  This receptor needs its own diagnostic (v3.4).

### Grid hot-spot (v2-style fit, no diel)

Fitted rate g/s, arranged as a 4×3 grid (south at top, west at left):

```
              lon -117.060   -117.040   -117.020
lat 32.555:      0.10         0.02       0.39
lat 32.575:      0.00      [  0.89  ]    0.00
lat 32.595:      0.38         0.72       0.37
lat 32.610:   [  0.87  ]      0.53       0.23
```

Two clear hot spots:
- **`ne11` at (32.575, -117.040) = 0.89 g/s** — directly **north of
  SAN YSIDRO** (~2 km). Cell goes essentially dark in neighbours, so
  NNLS is identifying it specifically. This is likely the dominant
  missing source.
- **`ne30` at (32.610, -117.060) = 0.87 g/s** — far north-west, on the
  Otay River / San Diego Bay edge. Probably an extension of the bay
  source field rather than a new physical source.
- **`ne21` at (32.595, -117.040)** = 0.72 g/s, between the two hot
  spots; could be either a real intermediate source or NNLS
  interpolating.

The east column is consistently low (max 0.39, mostly < 0.4) — sources
are not further east than ~−117.040.

### Total emission attributions

| Variant   | Total NE g/s | Notes                                            |
|-----------|-------------:|--------------------------------------------------|
| v2-style  | 4.51         | All temporal pattern absorbed into magnitude     |
| v3 single | 2.34         | Diel multiplier carries part of the pattern      |
| v3.1 per-arch | 1.57    | amp_water = 3.5 (at ceiling) amplifies more      |

The conservation makes sense — total emission × time-mean(diel) ≈ same
across variants.

### Per-archetype diel still doesn't help on holdout

v3.2 v3 (single-amp diel) gives the best SY holdout (0.200). v3.2 v3.1
(per-archetype diel) is slightly worse (0.194). With a richer source
field, the per-archetype split *still* isn't worthwhile — the
land/water amplitude separation appears to over-fit on train and lose
on holdout.

Verdict: single-amp diel is the sweet spot. v3.1's per-archetype
sophistication doesn't earn its keep.

### N-residual at SAN YSIDRO

| Variant   | N-resid (ppb) |
|-----------|--------------:|
| v3 (orig) | +11.79        |
| v3.1      | +11.79        |
| **v3.2**  | **+10.02**    |

About 15% reduction. Still 10 ppb of un-modeled signal — meaning the
grid isn't capturing everything. Worth a finer search (5-km grid →
1-km grid in the hot region).

## What this means

1. **The "missing source north of SAN YSIDRO" hypothesis is now
   strongly evidenced.** NNLS spontaneously absorbs 4.5 g/s into 12
   candidates with a clear spatial concentration at (32.575, -117.040).
   That's geographic structure, not noise.
2. **Otay Mesa industrial / cross-border at (32.575, -117.040) is the
   prime suspect.** This is on the US side just north of the border,
   roughly where the Otay Mesa industrial district begins. Worth
   ground-truthing against:
   - SDAPCD industrial emissions inventory
   - Tijuana / Mexicali cross-border emission reports
   - Any colocated complaint records in `data/complaints.parquet`
3. **The bay-area extension at (32.610, -117.060) is plausible.**
   Lat 32.610 / lon -117.060 is on the south edge of San Diego Bay,
   where bay-pond sources might extend.
4. **The remaining ~10 ppb N-residual implies there's still source
   structure we're not capturing.** Either finer-grid would help, or
   there's a temporal pattern (event-driven spikes) the smooth diel
   can't represent.

## What should be done next

1. **Refine grid in the hot region.** Drop 25 candidates in a 0.5 km
   spacing around (32.575, -117.040) and (32.595, -117.040). See if
   the cell concentration sharpens further.
2. **v3.3: spill exclusion.** The Mar 13-15 Stewart's Drain spill
   (peak 394 ppb) is in training. It likely inflates drain rates;
   excluding may give cleaner baseline parameters and better holdout
   generalisation.
3. **v3.4: IB CIVIC CTR diagnostic.** IB stuck at holdout r 0.087
   across all variants. Wind-sector decomposition + missing-source
   hunt analogous to Phase A but for IB.
4. **Ground-truth the (32.575, -117.040) hot spot physically.** Pull
   up a satellite view; check SDAPCD industrial inventory; flag any
   wastewater / agriculture / industrial point sources.
5. **Stop spending time on per-archetype diel.** Two experiments now
   show it doesn't help. v3.x going forward should use single-amp
   diel (the v3.2 "v3" variant).

## Limitations / caveats

- **The grid is coarse (~2 km spacing).** Hot cells indicate "somewhere
  around here" not specific facilities.
- **No physical ground-truthing.** Just because NNLS likes a cell
  doesn't mean there's a real source there — could be absorbing some
  other systematic error (wind data, receptor met).
- **Holdout SY r = 0.20 is still very low** compared to the v2 Mar 13-15
  reported number (0.12). Apr holdout is hard for everyone.
- **NE candidates are tagged `archetype="northeast"` and assigned to the
  "water" diel group.** That choice influences v3.1 (per-archetype)
  but not v3 (single-amp). Future variants might want to test
  northeast as `land` group.

## Files

- `output/summary.json` — metrics for all three variants
- `output/fitted_rates_v2.csv`, `output/fitted_rates_v3.csv`, `output/fitted_rates_v3_1.csv`
- `output/timeseries_train.csv`, `output/timeseries_holdout.csv`
- `output/wind_residuals_*.csv`
