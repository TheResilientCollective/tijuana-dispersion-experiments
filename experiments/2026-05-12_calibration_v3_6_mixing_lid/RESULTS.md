# Results — calibration v3.6 (nocturnal mixing-lid, Tier-1)

**Run on:** 2026-05-12
**Runtime:** ~6 s
**Status:** ❌ **Rejected — and decisively so.** Tier-1 limited-mixing
            Gaussian does not recover the calm-night extreme regime and
            slightly degrades the overall fit. The *reason* it fails is
            the important result: it proves the stagnation regime is
            non-advective and a lid (which scales an advected plume)
            cannot reach it.

## Numbers (Apr 1–14 holdout, single-amp diel)

| Receptor      | Metric   | baseline (no lid) | v3.6 (lid) | Δ      |
|---------------|----------|------------------:|-----------:|-------:|
| SAN YSIDRO    | Spearman | 0.182             | 0.172      | −0.010 |
| NESTOR (Berry)| Spearman | **0.525**         | 0.504      | −0.021 |
| IB CIVIC CTR  | Spearman | 0.473             | 0.457      | −0.016 |

Fitted lid scale `k_L = 165` (toward the *weak-lid* end of [10, 400]).
The optimizer deliberately chose a **large** mixing height — a strong
lid (small `L`) amplifies *all* nocturnal hours including the many
quiet ones, hurting the bulk fit more than it helps the rare extremes.

### Calm-night-extreme submetric @ Berry (the regime the lid targets)

Hours with night & wind < 3.5 m/s & Berry obs > 50 ppb:

| Quantity            | value |
|---------------------|------:|
| observed mean       | ~179 ppb |
| baseline pred mean  | ~9.4 ppb |
| **v3.6 pred mean**  | **~9.3 ppb** |
| baseline pred max   | 67 ppb |
| v3.6 pred max       | 69 ppb |

The lid moved the targeted prediction from 9.4 → 9.3 ppb mean (worse)
and 67 → 69 ppb max — i.e. **no material effect** against a ~179 ppb
truth.

## Why it fails (the result that matters)

A mixing lid is a **multiplicative factor on the advected footprint**:
`A_lid = A_unbounded × max(1, √(2π)σ_z/(L·V_unb))`. It can only amplify
a plume that the Gaussian model already delivers to the receptor.

But the May-10–11 / generalised stagnation analysis established that
during Berry's > 100 ppb events the wind is near-calm with **no
preferred direction**, and the river sources sit *downwind* of Berry —
so the unbounded footprint `A_unbounded ≈ 0` at Berry in exactly those
hours. And `max(1, …) × 0 = 0`.

**You cannot trap a plume that never arrived.** Any correction that
*scales* the advective footprint — diel (v3), per-archetype diel
(v3.1), more upwind sources (v3.2, v3.5), or a mixing lid (v3.6) — is
structurally incapable of producing the calm-night extremes, because
the advective footprint itself is zero there. This is now demonstrated
by five independent experiments converging on the same wall.

## What this means

1. **Tier-1 is conclusively insufficient.** Not "needs tuning" —
   structurally cannot reach the regime. `k_L` going to the weak-lid
   end is the optimizer correctly reporting that the lid only does
   harm (amplifying quiet advective nights) with no compensating gain.
2. **Tier-2 (box / accumulation model) is necessary, not optional.**
   The stagnation regime needs a model whose source term does **not**
   require an upwind advective path:
   `C[t] = C[t-1]·e^(−Δt/τ) + (E_local /(A·H_mix))·τ·(1−e^(−Δt/τ))`,
   active when `u < u_calm`, with a regime classifier handing off to
   the (limited-mixing) Gaussian when advection resumes. This is a new
   model class, not a footprint tweak — it belongs as a service-repo
   backend (`stagnation_box`) alongside `gaussian_plume`/`puff`/`hysplit`,
   per the backend protocol that already exists.
3. **The v3 plume-model line has reached its ceiling.** Best config
   remains v3.5 (NESTOR/Berry Spearman 0.525 on the advective bulk).
   Further plume-side experiments will not move the extreme regime.

## What should be done next

1. **Stop plume-side experiments.** Six experiments (v3 → v3.6) now
   agree the advective model is at its ceiling for the bulk and blind
   to the extremes.
2. **Scope a `stagnation_box` backend** in the service repo (design +
   PR, not an experiment): regime classifier on `(is_night,
   wind_speed, stability)`; well-mixed box with fitted ventilation
   timescale τ and an effective `H_mix(stability)`; emissions from the
   *local* river/valley aggregate (no directional routing). Validate
   it specifically on the 242 Berry > 100 ppb hours.
3. **Operational safety interim:** until the box backend exists, the
   service should *flag calm nocturnal hours as out-of-envelope*
   rather than emit a confident ~1–9 ppb when the truth can be
   150–750 ppb. This is a correctness issue worth raising as a
   service-repo issue now.
4. The independent calm-night **wind reanalysis** (NERR/TJRTLMET vs
   Open-Meteo) is still worth doing — it informs the box model's
   ventilation term and the regime-classifier threshold.

## Limitations / caveats

- Tier-1 used the standard "concentration can't fall below the
  fully-mixed value" form (`V_lim = max(V_unb, √(2π)σ_z/L)`). A
  full multiple-image-reflection sum would be marginally different at
  intermediate `σ_z/L` but cannot change the conclusion — the failure
  is `A_unbounded ≈ 0` in the target regime, independent of the lid
  formula.
- `L(t)` is parameterized from stability+wind proxies (no measured
  boundary-layer height). But since the lid had ~no effect, the
  parameterization choice is not the bottleneck.
- Single holdout window; the calm-night-extreme submetric is n≈
  (small) — but the mechanism (footprint ≈ 0 under flat-direction
  calm) is geometric and robust, not statistical.

## Files

- `output/summary.json` — baseline vs v3.6 holdout metrics + the
  calm-night-extreme submetric + fitted `k_L`
- `output/timeseries_holdout.csv` — obs / baseline / v3.6 per receptor
- `output/fitted_rates.csv` — baseline vs v3.6 per-source rates
