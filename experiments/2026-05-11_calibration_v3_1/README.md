# calibration v3.1 — per-archetype diel + relaxed bay cap + NE candidate sources

**Date:** 2026-05-11
**Status:** done
**Author:** autonomous (Claude Code session)
**Followup to:** [Phase A diagnostic](../2026-05-11_sy_north_residual_diagnostic/) and [v3](../2026-05-11_calibration_v3/)

## Question

The v3 experiment showed (a) diel modulation gives a modest fit improvement
and (b) the load-bearing W/SW SAN YSIDRO residual got *worse*. Phase A
diagnosed two root causes: the bay archetype cap was binding, and SAN
YSIDRO showed a uniquely strong N-sector signal that no existing source
could explain.

This experiment asks: does fixing the bay cap, adding candidate sources NE
of SAN YSIDRO, and giving the diel modifier separate amplitudes for land
vs water archetypes improve the holdout fit?

## Approach

Three concurrent changes on top of v3:

1. **Bay archetype upper bound raised 0.5 → 5.0 g/s.** v3 hit the cap on
   Otay River Outlet; relaxing lets NNLS attribute more mass there
   under N-wind nocturnal regimes.
2. **Two candidate sources at lat 32.580 and 32.595, lon -117.040** with
   a new `northeast` archetype (cap 2.0, prior 0.3). Tests the
   missing-source hypothesis from Phase A.
3. **Per-archetype diel multiplier.** Land sources (drain, channel)
   get one amplitude; water sources (estuary, bay, northeast) get
   another. Phase is shared. Outer optimization is now 3-D (was 2-D in
   v3).

The script also runs v2 (no diel) and v3 (single-amp diel) on the *same*
expanded source field and bounds, so the comparison isolates the
contribution of each piece.

## Acceptance criteria

- [x] v3.1 holdout SY r > v3 holdout SY r (any positive Δ counts as a win).
- [x] v3.1 holdout N-sector residual at SAN YSIDRO ≤ v3's (relax the W/SW
      acceptance from v3 — Phase A showed W/SW is no longer the
      dominant residual).
- [x] No regression on NESTOR-BES or IB CIVIC CTR holdout r > 0.05.

## How to reproduce

```bash
uv sync --extra dev --extra service
python scripts/fetch_data.py --only modeldata_h2s_nofill
cd experiments/2026-05-11_calibration_v3_1
uv run python run.py            # full Feb-Mar train + Apr holdout (~12 s)
uv run python run.py --quick    # Mar 13-15 only (~1 s)
```

## Dependencies

- `tijuana-dispersion` at `v0.3.0`
- `../../data/modeldata_h2s_nofill.parquet`

## Notes

The two NE candidate sources are *hypothesized*, not surveyed. We don't
have ground-truthing for their physical existence; we're testing whether
*the model wants* mass there. Treat as a proxy for "any source in this
region" rather than a specific facility claim.
