# Mixing-Height Experiment — Design

Status: **design** (not yet implemented). Written 2026-07-10 after the
2026-07-10 `mcmc_smc_calibration` result flagged model mis-specification.

## 1. Motivation

The first real Bayesian calibration (8-chain SMC, window Mar 13–16) could
**not** fit the observations:
- Posterior-predictive **94% coverage ≈ 3%** (target 94%).
- **NESTOR-BES under-predicted 3.4×** (obs mean 41 → pred 12); SAN YSIDRO
  over-predicted 2.8×.
- 7 of 11 parameters railed against their bounds even after widening —
  the signature of the model being unable to reach the required
  concentrations, so every knob runs to its limit.

The standing hypothesis in `calibration_status.md` (2026-05-12 nocturnal
mixing-lid entry + open questions): the plume assumes **unbounded vertical
mixing**, but under a shallow nocturnal boundary layer emissions are
**trapped near the ground**, amplifying ground-level concentration
5–10×. That under-prediction pattern is exactly what a missing lid would
produce, and it concentrates at the calm-night hours where NESTOR is most
under-predicted. This experiment adds the lid and tests whether it fixes
the fit.

## 2. The physics — mixing-lid Gaussian plume

Current `tijuana_dispersion/core.py::gaussian_plume_concentration` (ground
source H≈0, receptor z≈0) is unbounded above:

```
C = Q / (2π·u·σy·σz) · exp(-y²/2σy²) · [exp(-(z-H)²/2σz²) + exp(-(z+H)²/2σz²)]
```

With a mixing lid at height **L**, add reflections off the lid as well as
the ground (image sources at ±2nL):

```
vertical = Σ_{n=-N}^{N} [ exp(-(z - H - 2nL)²/2σz²) + exp(-(z + H - 2nL)²/2σz²) ]
```

N = 3–4 image pairs is plenty. Once the plume fills the mixed layer
(σz ≳ 1.6·L) the vertical profile is uniform and the sum collapses to the
**well-mixed limit**:

```
C_wellmixed = Q / (√(2π)·u·σy·L) · exp(-y²/2σy²)
```

Use the reflection sum for σz < 1.6L and the well-mixed form above it (the
two agree at the crossover). Backward-compatible: **L = None ⇒ current
unbounded behavior**, so the baseline is unchanged.

Why this produces the observed enhancement: a shallow nocturnal L confines
the plume; at receptors far enough downwind that σz has grown toward L,
ground concentration is amplified by ~`√(π/2)·σz/L` relative to unbounded
— multiples when L is small (100–200 m) and σz is a few hundred m.

## 3. The mixing-height model

No boundary-layer height is in the met data (nearest columns: `is_night`,
`stable_atm`, `cloud_cover`). So L is **not observed** — we model it and
let calibration fit it. First cut: a **two-regime step**, keyed off the
`is_night` flag we already pass to `MetSpec`:

```
L(t) = L_night   if is_night(t) else L_day
```

- **`L_night`**: fittable, prior `U(50, 500) m` (nocturnal boundary layer).
  This is THE parameter of interest.
- **`L_day`**: fix at `1500 m` initially. During convective daytime σz
  rarely reaches L, so the lid is ~inactive and `L_day` barely matters —
  fixing it keeps the experiment to one new parameter. (Promote to
  fittable only if a later run shows daytime sensitivity.)

Refinement (later, if warranted): blend on `stable_atm` or a continuous
stability index instead of the binary `is_night`, or a smooth diel curve.

Decisive check on physical plausibility: if the **posterior `L_night`
concentrates in ~50–300 m** (real nocturnal BL) rather than running to a
bound, the fitted lid is physically credible, not just a fudge factor.

## 4. Implementation plan (Approach A — proper fix, cross-repo)

**tijuana-dispersion** (branch off `v0.4.0`, github.com/theresilientcollective/tijuana-dispersion):
1. Add `mixing_height_m: float | None = None` to `MetSpec` (schemas) and
   the internal `MetCondition`.
2. In `gaussian_plume_concentration`, when `mixing_height_m` is set, replace
   the `vertical` term with the reflection sum / well-mixed limit (§2).
   Keep `None` → unchanged.
3. Unit tests: (a) `L=None` reproduces current output exactly; (b) large L
   ≈ unbounded; (c) small L enhances ground conc; (d) well-mixed limit
   matches the reflection sum at the crossover. Bump to `v0.5.0`.

**tijuana-dispersion-experiments** (this repo):
4. Repoint the `service` extra dep to the new tag/branch; rebuild image.
5. `nrp/sobol.py::make_drivers_and_met`: set `mixing_height_m` per hour from
   `L_night`/`L_day` and `is_night`. Source `L_night`/`L_day` from a config
   (so the baseline path can leave it None).
6. Add `mixing_height_night_m` to the calibration parameter set
   (`PARAM_RANGES`, prior `U(50, 500)`), gated so the baseline 11-param
   studies are untouched.

## 5. Comparison plan (baseline vs treatment)

- **Baseline** (done, on record): 11-param, unbounded plume →
  `runs/sobol/…N8192…` + `runs/mcmc/…8chains_500p…`. Verdict: no fit
  (coverage 3%, NESTOR 3.4× under).
- **Treatment**: 12-param (11 + `mixing_height_night_m`), lidded plume.
  - **Sobol** on 12 params: does `mixing_height_night_m` show meaningful
    ST, especially on the corr/rms metrics at NESTOR? (If the lid matters,
    it should rank up.)
  - **MCMC**: the decisive test — per-receptor **posterior-predictive
    RMSE + 94% coverage**, focused on NESTOR nocturnal hours. Success =
    NESTOR under-prediction shrinks, coverage rises toward 94%, and the
    previously-railing params relax to interior values (the lid gives the
    model the "reach" it lacked).
  - **Physical-plausibility gate**: posterior `L_night` ∈ ~50–300 m.

Report both through the existing pipeline (`runs/sobol/…`, `runs/mcmc/…`);
log the comparison as a new `calibration_status.md` entry.

## 6. Open design decisions (resolve before coding)

1. **1 vs 2 new params** — fit `L_night` only (recommended) or also
   `L_day`?
2. **Regime key** — binary `is_night` (recommended first) vs `stable_atm`
   vs a smooth diel curve.
3. **σz for the well-mixed threshold** — reuse core's `briggs_sigma`
   (already there) — no new stability code needed.
4. **Scope** — full 12-param Sobol+MCMC re-run (clean comparison, more
   compute) vs a cheaper MCMC-only treatment first (faster signal). The
   500-particle MCMC + pools/retry makes either feasible.
5. **obs_sigma** — the baseline's fixed `obs_sigma=10` made coverage
   meaningless. Consider estimating `obs_sigma` (or per-receptor) *in the
   same treatment run*, so a coverage improvement is trustworthy. This may
   be the higher-leverage change and could be tested alongside, or first.
