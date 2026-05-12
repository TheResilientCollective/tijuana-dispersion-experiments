# calibration v3.2 — NE candidate grid sweep

**Date:** 2026-05-12
**Status:** done
**Author:** autonomous (Claude Code session)
**Followup to:** [v3.1](../2026-05-11_calibration_v3_1/) and [Phase A](../2026-05-11_sy_north_residual_diagnostic/)

## Question

v3.1 added two hypothesized NE-of-SAN-YSIDRO sources at fixed locations
and they absorbed ~1.8 g/s combined — but the SY N-residual stayed at
~12 ppb mean. Two possibilities: (a) the source is real but at a
different location than the two test points, or (b) the source is
genuinely ~12 ppb of unmodelled background. A 12-cell grid sweep across
the Otay Mesa / cross-border region tells us which.

## Approach

Replace v3.1's 2 NE candidates with a 4×3 = 12 grid over the lat range
32.555–32.610 and lon range −117.060 to −117.020, spacing ~0.02° (~2 km).
Per-archetype diel modulation, bay cap, and outer optimization all
inherit v3.1's setup.

Source names use `ne00`…`ne32` (no underscore-before-digits) so the
smoothness penalty doesn't apply between adjacent grid cells — NNLS is
free to pick winners.

## Acceptance criteria

- [x] At least one grid cell absorbs a meaningful rate (> 0.3 g/s).
- [x] Holdout SAN YSIDRO r ≥ v3.1's 0.115.
- [x] The spatial pattern of fitted rates suggests a coherent source
      location (not random spread).

## How to reproduce

```bash
uv sync --extra dev --extra service
python scripts/fetch_data.py --only modeldata_h2s_nofill
cd experiments/2026-05-12_calibration_v3_2
uv run python run.py            # ~12 s
uv run python run.py --quick    # ~2 s
```

## Dependencies

- `tijuana-dispersion` at `v0.3.0`
- `../../data/modeldata_h2s_nofill.parquet`

## Notes

The grid is a coarse hypothesis-test, not a real source inventory. A
"hot" cell means *somewhere in the surrounding ~2 km* is producing
emissions; it doesn't claim a specific facility.
