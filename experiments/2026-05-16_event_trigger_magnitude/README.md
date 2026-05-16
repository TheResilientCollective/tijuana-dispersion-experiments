# Event-trigger magnitude — can a trigger recover recall@100?

**Date:** 2026-05-16
**Status:** done — **decisive negative for exogenous; capstone of the arc**
**Author:** autonomous (Claude Code session)
**Follows:** `box_driver_calibration` (ranker, not magnitude); closes the calm-night magnitude line

## Question

`box_driver_calibration` validated the box→temperature driver as a
calm-night *ranker* but recall@100 = 0 (extremes under-predicted
~17–20×). The one remaining lever — explicitly *not* more
emission-driver tuning — is an **episodic trigger** that boosts the
box's local emission on event hours, via the **shipped #6
`substrate` multiplier hook**:

    E_local(t) = E0·Q10^((T−T_ref)/10) · [1 + (B−1)·1{trig(t) ≥ θ}]

**Does any episodic trigger recover recall@100 on held-out Berry
stagnation hours — and is the usable trigger *exogenous* (forward) or
only *autoregressive* (nowcast)?**

## Approach

Calibrated driver (rank-optimal Q10=5, τ=12), same Berry +
chronological 70/30 split as the three prior experiments. recall@100
is gameable by blanket boosting, so the train objective is **Youden's
J = recall − FPR** at 100 ppb; held-out recall/precision/FPR/F1 +
Spearman all reported. **EXOGENOUS** triggers (flow/SBIWTP/precip —
forward-usable) are separated from the **AUTOREGRESSIVE reference**
(`h2s_lag_1h`, uses observed H2S → not forward-usable, reported only
to bound the ceiling). θ = train percentile; B from a grid; E0
closed-form on train.

## Reproduce

```bash
uv run python experiments/2026-05-16_event_trigger_magnitude/run.py
```

## Headline

**No exogenous trigger recovers anything**: best forward-usable
trigger → recall@100 = **0.00**, precision = 0.00 (both regimes;
train Youden J ≈ 0.02 — nothing fires on the right hours). The
**autoregressive** reference (`h2s_lag_1h`) reaches recall ≈ **0.21**,
precision ≈ **0.35**, Spearman ≈ 0.44 — modest, and *not* forward-
usable. **Conclusion of the whole arc:** Berry's calm-night extremes
are unpredictable from any *exogenous* signal in this dataset; the
only magnitude skill is **autoregressive persistence**, i.e. a
nowcast — a different product class from the forward model. See
RESULTS.md.
