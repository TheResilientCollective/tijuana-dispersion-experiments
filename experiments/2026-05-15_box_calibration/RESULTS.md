# Results — stagnation-box calibration vs Berry's >100 ppb hours

**Run on:** 2026-05-15
**Runtime:** ~30 s
**Status:** ❌ **Negative result.** Calibrating the shipped calm-night
box does not give the regime skill. The box is *necessary* (it removes
the geometric Gaussian failure) but *not sufficient* (constant lumped
emission cannot reproduce the extremes). 🎯 Identifies the next model
component: an emission-driver term, not more dispersion physics.

## Setup

- 12 964 Berry (NESTOR - BES) hours; **242** with H2S > 100 ppb.
- Held-out fraction: **0.30** (chronological; never fit on test).
- Fixed at shipped physical defaults: `H_mix` table
  (A 1600 → F 50 m), `area = 4.0e6 m²`. Amplitude is identifiable
  only as the lumped group `E_local/(A·H_mix)`, so only `E_local`
  (closed-form linear) and `τ` (grid, via dynamics) are fit.

## The numbers (held-out test set)

| Classifier | n test | τ\* | E_local\* (g/s) | Spearman | Rank-skill **ceiling** | recall@100 | median pred / obs at >100 |
|---|--:|--:|--:|--:|--:|--:|--:|
| `is_stagnation` (is_night & wind<2.5) | 543 | **12.0 (pegged)** | 0.312 | 0.120 | **0.127** | **0.00** | 10.6 / 177.1 ppb |
| `stable_atm` (reanalysis-preferred) | 1333 | **12.0 (pegged)** | 0.307 | 0.186 | **0.218** | **0.00** | 8.8 / 167.4 ppb |

- **Rank-skill ceiling is the decisive number.** Spearman is invariant
  to the amplitude fit, so the *best* any `(τ, E_local)` in the box
  family can reach on held-out Berry stagnation hours is ≈ **0.13**
  (operational) / **0.22** (`stable_atm`). No calibration of `E_local`
  can beat this — it is a property of the box's *shape*, not the fit.
- **recall@100 = 0.00.** The calibrated box lifts **none** of the 71
  (operational) / 119 (`stable_atm`) held-out >100 ppb hours above
  100 ppb. Median prediction at those hours is ~9–11 ppb against an
  observed median of ~167–177 ppb — a **~17× shortfall**.
- **false-positive rate@100 = 0.00** too: the box never predicts
  >100 ppb *anywhere*. It is not trading recall for false alarms — it
  simply has **no dynamic range** at the LSQ-optimal amplitude.
- **τ pegs at the 12 h grid maximum** for both classifiers. The box
  wants ever-more integration to smooth toward the bulk; extending the
  grid cannot help (rank skill is amplitude/τ-bounded at ~0.13–0.22).

## Event validation (shipped dispatch, May 10–11, end-to-end)

```
window 2026-05-10 18:00 .. 2026-05-11 08:00   (15 h, 4 flagged stagnation)
observed peak            177.1 ppb
pure Gaussian peak         0.16 ppb   (plume routed away — geometric miss)
calibrated box dispatch    7.9  ppb   (dispatch="regime", wired path)
```

The calibrated regime dispatch lifts the calm-night event **~50×**
over Gaussian (0.16 → 7.9 ppb) — the box physics is the right
*direction* and the shipped `run_forward` dispatch works end-to-end —
but it is still **~22× short** of the 177 ppb observed peak.

## What this means

1. **The box is necessary but not sufficient.** It correctly removes
   the *geometric* Gaussian failure ("plume routed away on calm
   nights" — the v3→v3.6 / calm-night-reanalysis finding). Direction
   is right; magnitude and ranking are not.
2. **The missing variance is emission-driven, not ventilation-driven.**
   A *constant* lumped `E_local` modulated only by atmospheric
   stability produces a slowly-varying envelope. It cannot pick *which*
   calm nights spike to 100–750 ppb, because that selection lives in
   the upstream **H2S production** (river flow, SBIWTP loading,
   temperature), not in the mixing depth. One amplitude cannot serve
   both the ~1–10 ppb calm bulk and the 752 ppb extreme.
3. **`stable_atm` is again the better regime signal** (test Spearman
   0.19 vs 0.12; ceiling 0.22 vs 0.13; more regime hours). Independent
   corroboration of the 2026-05-15 calm-night reanalysis
   recommendation to fold `stable_atm` into the classifier.
4. **This closes the "bare box" line** the way `calibration_v3_6`
   closed the advective line. Negative, recorded so it is not retried:
   calibrating the box's 2 free parameters is not the lever.

## Next

1. **Emission-driver term (the actual lever).** Couple the box's
   `E_local` to the upstream production proxies already in
   `modeldata_h2s_nofill` (`sbiwtp_*`, `flow_*`, `temperature_2m`,
   the diel terms). This is an *emissions-model* extension, candidate
   for the service `emissions.py` skeleton — design/issue, not done
   here. The box recurrence stays; `E_local` becomes time-varying.
2. **Service:** keep the shipped box (it is the correct regime
   *structure* and the dispatch works); do **not** hard-wire these
   uncalibrated `τ`/`E_local` as "tuned". Recommend a service-repo
   note that box amplitude must come from an emission-driver model.
3. **Pin bump (PR-gated):** experiments-repo `tijuana-dispersion`
   extra is `@v0.3.0`, which predates the box; bump to a release tag
   that includes issue #3 so this experiment is reproducible without
   the local editable install. `pyproject.toml` edit → PR per
   AGENTS.md; flagged, not done here.

## Limitations

- Single lumped local source; `A` and `H_mix` held at physical
  defaults (necessary — amplitude is otherwise unidentifiable from a
  single receptor). The negative conclusion is robust to these because
  it rests on the **amplitude-invariant rank-skill ceiling**, not on
  any amplitude/area choice.
- Calibrated and evaluated on the same site (Berry); the question was
  specifically Berry's extremes. Train/test is chronological, so
  seasonal structure could differ across the split — but the ceiling
  is low on *both* train and test, so this does not rescue it.
- `τ` grid capped at 12 h; pegging is reported honestly. Larger `τ`
  cannot raise the rank ceiling (amplitude/shape-bounded), so the grid
  range is not the limitation.

## Files

- `output/summary.json` — full calibration + event-validation metrics
