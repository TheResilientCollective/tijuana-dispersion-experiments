# Results — calibration v3.1

**Run on:** 2026-05-12 (PT)
**Runtime:** ~12 s (full fit + holdout eval, all three variants)
**Status:** ✅ **Acceptance criteria met.** Three variants compared on
            the same source field. v3.1 marginally beats v3; the bulk
            of the lift over the original v3 experiment comes from the
            structural changes (NE candidates + relaxed bay cap), not
            from the per-archetype diel sophistication.

## Question

Does fixing the bay cap + adding NE candidate sources + per-archetype
diel improve over v3's fit, and which piece does the work?

## Key findings

### Headline numbers (Apr 1-14 holdout, 919 valid obs)

| Receptor      | original v3 | v2† | v3‡ | v3.1§ |
|---------------|------------:|----:|----:|-----:|
| SAN YSIDRO    | 0.041       | **0.092** | **0.114** | **0.115** |
| NESTOR - BES  | 0.201       | 0.200 | 0.211 | 0.209 |
| IB CIVIC CTR  | 0.091       | 0.084 | 0.086 | 0.087 |

† v2 baseline with v3.1's source field (NE candidates included, bay cap 5.0). Apples-to-apples comparison vs the original v3 experiment's v2 (which used the smaller source field) is the "original v3" column.
‡ Single-amp diel on the v3.1 source field — what v3 would have given if it had the NE candidates + relaxed bay cap.
§ Per-archetype diel (this experiment's headline variant).

**Reading the table column by column:**

- **Adding NE candidates + relaxing bay cap alone (the "v2" column) more
  than doubles SAN YSIDRO holdout r** (0.041 → 0.092). This is the largest
  single improvement seen across any v3-family change so far.
- **Single-amp diel on top adds ~0.022 to SY** (v3 column).
- **Per-archetype diel adds essentially nothing on holdout SY** (+0.001),
  though it changes the train fit shape (see below).
- NESTOR and IB are essentially unchanged across columns — these
  receptors are insensitive to the NE / bay changes (geometrically: bay
  is north of NESTOR, NE candidates are far east of IB).

### v3.1 fitted parameters

- `diel_amplitude_land`  = 1.71 (drain + channel)
- `diel_amplitude_water` = 3.49 — **at upper bound of 3.5** (estuary + bay + northeast)
- `diel_phase_hours`     = 4.23 (peak ~04:14 AM)
- 68 outer Nelder-Mead evaluations to converge.

`amp_water` hitting the upper bound is a signal — the water-side sources
want even stronger nocturnal amplification than the bound allows. v3.2
should raise this ceiling and see if performance keeps climbing.

### NE candidate fitted rates (g/s)

| Source                  | v2† | v3 | v3.1 |
|-------------------------|----:|----:|-----:|
| Otay Mesa Industrial S  | 0.83 | 0.51 | 0.30 |
| Otay Mesa Industrial N  | 0.98 | 0.63 | 0.37 |
| San Diego Bay (Otay)    | 0.90 | 0.59 | 0.36 |
| San Diego Bay (Fruitdl) | 0.40 | 0.26 | 0.15 |

The northeast candidates get **0.83 + 0.98 = 1.81 g/s combined** in the
v2-style (no-diel) fit — comparable to a single drain source. Both are
well below their 2.0 cap, so the model isn't being constrained. The
fact that NNLS spontaneously puts ~2 g/s into hypothesized sources NE
of SAN YSIDRO is strong indirect evidence that *something* is producing
emissions there.

As diel-amplification kicks in (v3 and v3.1), baseline rates drop
because the diel multiplier carries more of the temporal pattern. Net
emission is roughly conserved: v2's 0.98 ≈ v3.1's 0.37 × peak amp
(~2.25 effective).

### Wind-sector residuals at SAN YSIDRO

| Sector group                | v2 (new)† | v3 | v3.1 |
|-----------------------------|----------:|---:|-----:|
| W/SW/WSW (v2-era diagnostic)| +1.39 ppb | +1.81 | +1.71 |
| N/NNE/NE/ENE/E/NNW (Phase A)| +11.82 ppb | +11.79 | +11.79 |

The N-sector residual barely moved. The NE candidates absorbed some
mass but the residual stays around 12 ppb — meaning the candidates
either aren't in the right place, are too rate-limited even at the
2.0 cap, or there are *multiple* missing sources spread further north.

## What this means

Three concrete updates to project beliefs:

1. **There almost certainly is a real source NE of SAN YSIDRO.** When
   given two candidate locations in the right region, NNLS readily
   attributes ~1-2 g/s to them — that's not noise. It's worth
   investigating physically (Otay Mesa industrial inventory, cross-
   border emissions registry).

2. **The bay archetype cap of 0.5 g/s was too tight.** Otay River
   Outlet readily takes 0.9 g/s in the v2-style fit. The default
   `ARCHETYPE_BOUNDS_G_S` in the service repo's `calibration.py`
   should probably be updated to 2.0+ for `bay`.

3. **Per-archetype diel was the wrong simplification.** Splitting
   amplitudes into land vs water gives a fit very similar to the
   single-amp version. The model isn't currently expressive enough for
   the per-archetype split to matter — most likely because we're still
   missing the spatial pattern (specific source locations), and a
   uniform diel shape masks that. Per-archetype phase might still
   matter; per-archetype amplitude alone doesn't.

## What should be done next

In rough priority order:

1. **v3.2: expand the NE candidate grid.** Place 6-9 candidate sources
   across the Otay Mesa / cross-border area (lat 32.55-32.62, lon
   -117.06 to -117.02). NNLS picks which ones light up; clusters
   indicate real source locations. Don't constrain by archetype too
   tightly — the placeholder archetype is "northeast" but actual sources
   may behave differently.
2. **v3.3: raise `amp_water` ceiling.** Currently v3.1 fits at the 3.5
   bound. Try [1, 6] and see if it keeps climbing or stabilises.
3. **v3.4: spill-event treatment.** Mar 14-15 spike is in training and
   inflates several drain rates. Hold out the spill week from
   training, refit, see how much of the train r is "real" vs
   spill-event-bound.
4. **IB CIVIC CTR diagnostic.** Holdout r is stuck at ~0.09 regardless
   of variant. This receptor needs its own investigation — what does
   IB see that the model doesn't?
5. **Update service-repo `ARCHETYPE_BOUNDS_G_S` defaults.** A PR in the
   service repo to set `bay: 2.0` would let future calibrations skip
   the manual override.

## Limitations / caveats

- **NE source locations are hypothesized.** The model wants mass there,
  but we don't have ground truth that those specific lat/lon points
  contain real sources. The grid sweep in v3.2 will narrow it down.
- **v3.1 vs v3 difference on holdout is < 0.005 r.** Per-archetype
  diel is *not* a meaningful improvement on its own in this fit. It
  may help once the spatial picture is more correct.
- **v3.1 fits `amp_water` at its upper bound (3.5).** This is a
  detected ceiling effect; conclusions about water-side diel amplitude
  are conservative.
- **Mar 13-15 spill event remains in training.** Drain rates may
  still be inflated. The next experiment should hold it out.
- **Holdout RMS still huge for NESTOR-BES** (84 ppb). r=0.21 captures
  some pattern but the magnitudes are off by ~5-10×. Either source
  rates are wrong or there's a magnitude-scaling issue elsewhere.

## Files

- `output/summary.json` — machine-readable metrics for all three variants
- `output/timeseries_train.csv`, `output/timeseries_holdout.csv` — obs + 3 predictions per receptor per hour
- `output/fitted_rates_v2.csv`, `output/fitted_rates_v3.csv`, `output/fitted_rates_v3_1.csv`
- `output/wind_residuals_v2.csv`, `output/wind_residuals_v3.csv`, `output/wind_residuals_v3_1.csv`
