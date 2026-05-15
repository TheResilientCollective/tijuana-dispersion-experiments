# calibration v3.6 — nocturnal mixing-lid (Tier-1 limited-mixing Gaussian)

**Date:** 2026-05-12
**Status:** done
**Author:** autonomous (Claude Code session)
**Followup to:** may1011_event_analysis (calm-night stagnation = the
unmodelled regime)

## Question

The May-10–11 / generalised stagnation finding showed Berry's > 100 ppb
events are calm-night, no-preferred-direction accumulation that a
steady-state Gaussian plume can't represent. Tier-1 of the
mixing-height design adds a reflecting lid at height `L(t)` so the
ground concentration can't fall below the fully-mixed value
`Q/(√(2π)·u·σ_y·L)`. Does trapping the plume under a collapsed
nocturnal boundary layer recover the extreme regime?

## Approach

- Limited-mixing treatment as a **multiplicative factor on the
  unbounded footprint** (stays linear in emission rate → reuses the
  bounded-NNLS machinery, same trick as the diel multiplier):

  `factor[t,r,s] = max(1, √(2π)·σ_z / (L[t]·V_unbounded))`

- `L(t) = clip(k_L · max(u,0.5) · s(stability), 30, 2000)` m,
  `s = {A:2.5,B:2.0,C:1.5,D:1.0,E:0.5,F:0.3}`; `k_L` fitted in the
  outer loop with single-amp diel (amp, phase).
- v3.5 source field + single-amp diel. Reuses v3.5's data/source/NNLS
  code by import (DRY). Geometry (σ_z, V_unbounded, unbounded ppb
  footprint) recomputed locally, mirroring `core.gaussian_plume_concentration`
  exactly so the lid ratio is consistent.
- Compares **baseline (no lid = v3.5)** vs **v3.6 (lid)** on the Apr
  holdout, headline Spearman, plus a **calm-night-extreme submetric**
  at Berry (night & wind<3.5 m/s & obs>50 ppb) — the regime the lid
  targets.

## Result preview

**Rejected, and it confirms the structural diagnosis.** The lid does
nothing for the calm-night extremes and slightly degrades the overall
fit. Reason: a lid multiplies the *advected* footprint, but during
Berry's flat-direction stagnation events the river sources are
geometrically downwind so that footprint is ≈0 — `factor × 0 = 0`.
You cannot trap a plume that never arrived. This proves Tier-2 (the
non-advective box/accumulation model) is necessary, not optional. See
RESULTS.md.

## Reproduce

```bash
uv sync --extra dev --extra service
python scripts/fetch_data.py --only modeldata_h2s_nofill
cd experiments/2026-05-12_calibration_v3_6_mixing_lid
uv run python run.py
```
