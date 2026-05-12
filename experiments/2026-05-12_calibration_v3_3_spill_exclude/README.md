# calibration v3.3 — spill exclusion (negative-result experiment)

**Date:** 2026-05-12
**Status:** done
**Author:** autonomous (Claude Code session)
**Followup to:** [v3.2](../2026-05-12_calibration_v3_2/)

## Question

The Mar 13-15 Stewart's Drain spill (peak 394 ppb at NESTOR) sits in
the training window. The hypothesis from earlier RESULTS files was
that this inflates fitted drain rates and degrades holdout
generalisation. Does excluding the spill hours from training give
lower drain rates and better holdout fit?

## Approach

Same source field, archetype bounds, and outer optimization as v3.2.
Single change: mask Mar 13 12:00 → Mar 16 00:00 PT in the training
obs array (60 hours × 3 receptors = 180 obs cells dropped). Met
series stays intact so train-prediction diagnostics still exist;
only NNLS sees the masked obs.

## How to reproduce

```bash
cd experiments/2026-05-12_calibration_v3_3_spill_exclude
uv run python run.py
```

## Result preview

Spill exclusion **hurts** holdout fit — see RESULTS.md. Null result.

Going-forward recommendation: keep the spill in training. The signal
it carries generalises to the non-spill nocturnal regime more than the
hypothesis predicted.
