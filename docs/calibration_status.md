# Calibration Status Log

This is the running log of where the H₂S dispersion calibration stands. **Read this first** at the start of any session. Update it after every meaningful experiment.

Format for each entry:

```
## YYYY-MM-DD — <experiment short name>

**Question**: ...
**Result**: ...
**State change**: <what we now believe vs before>
**Next**: <what experiment this points toward>
```

Don't delete old entries. The log is the project's memory.

## Receptor identity (READ THIS — confirmed 2026-05-15)

The H₂S monitor `site_name` codes are not self-explanatory. Mapping:

| `site_name`    | What it actually is                         |
|----------------|---------------------------------------------|
| `NESTOR - BES` | **Berry Elementary School** (Nestor nbhd, San Diego) |
| `SAN YSIDRO`   | San Ysidro monitor                          |
| `IB CIVIC CTR` | Imperial Beach Civic Center                 |

`BES` = Berry Elementary School. If a stakeholder asks about "Berry
Elementary," they mean `NESTOR - BES`. (A 2026-05-12 analysis briefly
mis-concluded Berry was absent from the data after a naive substring
search — it is in fact our primary, best-fit receptor.)

---

## 2026-07-11 — drainage_kernel + tide_ebb implemented; forward validation positive

**Implementation** (`tijuana-dispersion` `feat/receptor-box` @ `03bf5d5`,
69 tests pass):
- `stagnation.drainage_weighted_e_local(sources, receptor, λ_along,
  λ_cross, bearing)`: directional kernel — upstream sources decay on
  λ_along down the drainage axis; abeam/downstream on the short λ_cross.
  Exposed via `StagnationBoxSpec.drainage_bearing_deg` (valley ≈ 280°)
  + `lambda_cross_m`.
- Tide-ebb culvert term (derivative form, per user decision):
  `EmissionDrivers.tide_rate_m_h` (default 0 = inert; caller computes
  d(tide)/dt across hours), `EmissionParameters.a_ebb` +
  `ebb_source_names`, `f_tide_ebb = 1 + a_ebb·max(0, −d(tide)/dt)`.
  Self-lagging; the box residence time supplies the remaining lag.

**Forward validation** (Mar 13–16, baseline posterior-mean emissions,
bearing 280°, Saturn Blvd Bridge as the ebb source — NO fitting):
| λ_cross | a_ebb | N/SY | IB/SY | corr(NESTOR, calm hrs) |
|---|---|---|---|---|
| (isotropic kernel, any λ) | 0 | 1.0 | — | −0.03 |
| 500 | 0 | 2.2 | 0.6 | −0.03 |
| 500 | 40 | 5.7 | 1.3 | +0.33 |
| 500 | 100 | **10.9** | **2.3** | **+0.37** |
| obs | | **14.9** | **2.7** | (tide-lag corr +0.60) |

The two structures together approach the observed calm-night receptor
pattern AND give the predictions tide-locked temporal skill inside the
stratum, where every previous model form was flat. Absolute scale is low
(NESTOR 3.4 vs 149.7 ppb) but that's the uncalibrated τ/area and
`baseline_scale` (bounds allow 200×) — the *pattern* was the hard part.
a_ebb ~ 40–100 means peak-ebb Saturn emission 15–40× its baseline, i.e.
the culvert drop dominates the calm-night budget — consistent with the
field description (the drop is the aeration event; everything else is
quiescent ponded water).

**Next**: wire calibration: (1) experiments repo — compute
`tide_rate_m_h` in `make_drivers_and_met`, pass `stagnation_box` spec +
`a_ebb`/`ebb_source_names` through `predict_concentrations`, config-
gated like the mixing-height treatment; new params `a_ebb`, `λ_along`,
`λ_cross`, `tau_h` (bearing fixed at 280°). (2) Re-pin image to the new
service commit; MCMC treatment v2 on NRP (obs_sigma fixed at 10 —
lesson from the mhlid_fitsig run). (3) Multi-window tide-lag
replication to de-alias the 12.4 h/12 h cycle overlap.

## 2026-07-11 — saturn_culvert_field_knowledge + tide-lag check (mechanism identified)

**Field knowledge** (user, 2026-07-11): the calm-night driver at NESTOR
is **drainage flow**, fed by the **Saturn Blvd culvert**: the culvert
ponds the river upstream, and at low tides there is a **drop from the
culvert** (turbulent aeration → H₂S stripping). So the two candidate
structures from the λ-sweep entry are *coupled*: Saturn Blvd is a
tide-modulated hotspot, and nocturnal drainage flow delivers it
down-valley to NESTOR (Berry).

**Empirical check** (Mar 13–16 window; `tide_height` is already in the
parquet and in `EmissionDrivers.tide_height_m`): NESTOR calm-night H₂S
vs tide —
- lag 0: corr ≈ −0.10 (calm night), −0.35 (all night)
- **lag 2–3 h: corr +0.60 (calm night)**, +0.40..0.49 (all night)
- i.e. concentrations peak a few hours *after* high tide, **on the
  ebb** — consistent with the culvert mechanics (high tide submerges
  the drop and backs up ponding; the falling tide re-exposes the drop
  and drains the ponded volume over it) plus down-valley transport lag.
- Low-vs-high tide split, calm nights: 167 vs 128 ppb (NESTOR).
- *Caveat*: n=15 calm-night hours in one 3-day window; the ~12.4 h tide
  vs 12 h night cycle aliases — treat as supporting, not proof. A
  multi-window replication is cheap once the model form exists.

**Proposed model form** (next implementation, both calibratable through
the existing pipeline):
1. **Tide-ebb hotspot** (emissions side; `EmissionDrivers.tide_height_m`
   already wired): per-source multiplier for `Saturn Blvd Bridge` —
   `f_culvert(t) = 1 + a_ebb · max(0, −d(tide)/dt)` (or a lagged-tide
   sigmoid), `a_ebb` calibratable. Zero new data plumbing.
2. **Drainage kernel** (box side; chassis from `feat/receptor-box`):
   replace the isotropic `exp(−d/λ)` with an along-valley directional
   weight on stagnation hours — receptors accumulate *upstream* channel
   sources with decay length `λ_valley` down the drainage axis. NESTOR
   (down-valley) then integrates the Saturn/Hollister/Dairy Mart chain;
   SAN YSIDRO (up-valley) does not — which is what the 14.9× ratio needs.

## 2026-07-11 — receptor_box_lambda_sweep (kernel built; inventory geometry can't split NESTOR from SY)

**Question**: Does a receptor-dependent stagnation box — per-receptor
`E_r = Σ_s rate_s · exp(−d_rs/λ)` — reproduce the calm-night receptor
pattern (obs NESTOR 149.7 / IB 27.3 / SY 10.1, i.e. N/SY ≈ 15×)?

**Implementation (done)**: `tijuana-dispersion` branch
`feat/receptor-box` @ `9a53940` (v0.4.0, schema 0.5.0):
`stagnation.distance_weighted_e_local`, `StagnationBoxBackend(lambda_m=…)`,
`ForwardRunRequest.stagnation_box` (λ, tau_h, area_m2 — all calibratable),
composes with the temperature driver; `λ=None` is v1 byte-identical;
62 tests pass; per-test cache isolation added. (mypy hook pre-broken at
base 73161d9 — numpy stubs drift, skipped.)

**Result of the λ sweep** (λ ∈ {250…4000} m, baseline posterior-mean
emissions, 16 calm-night hours): the kernel moves IB down (IB/SY
0.16–0.75 vs obs 2.7) but **NESTOR/SY stays ≈ 1.0 at every λ** (obs: 14.9).
Why: SAN YSIDRO is *also* channel-adjacent — CDLP E (1.22 km), CDLP W
(1.35 km), Dairy Mart Bridge (1.66 km) vs NESTOR's Saturn Blvd Bridge
(0.89 km). Archetype-summed kernel weights are near-identical for the
two receptors at every λ (e.g. λ=1000 m: channel 0.82 vs 0.84, total
1.25 vs 1.26). **No distance decay over the current inventory — even
with free per-archetype weights — can produce NESTOR ≫ SY.**

**State change**: The calm-night NESTOR anomaly is not explainable by
horizontal proximity to the *inventoried* sources with *shared archetype
rates*. Two candidate structures remain:
1. **Per-source hotspot**: the river at the Saturn Blvd crossing is a
   locally much stronger emitter than the CDLP/Dairy Mart channel
   segments (ponding/low-flow turbulence). Then a per-source rate
   multiplier for Saturn Blvd Bridge — not a smooth archetype weight —
   is the missing parameter.
2. **Receptor-side valley confinement**: Berry School sits on the
   Tijuana River valley floor where nocturnal cold-air drainage pools;
   the SY monitor sits higher on the slope, above the shallow drainage
   layer. Then the box needs a per-receptor H_mix / valley-membership
   term, not (only) a distance kernel.
These predict different things: (1) says NESTOR's excess should follow
Saturn-Blvd-specific flow conditions; (2) says it should follow
stability/drainage nights regardless of which source is active, and
that *any* valley-floor receptor would see it while mesa receptors
don't.

**Next**: Needs field/terrain input to choose (elevations of the three
monitors vs the valley floor would already discriminate). Kernel is
merged-ready either way — it's the right chassis for both, and λ+tau
remain calibratable in the eventual MCMC.

## 2026-07-11 — sigmaz_sweep + regime stratification (the misfit lives in the stagnation box)

**Question**: Is the σz scheme (Briggs rural over-diluting on stable
nights) the missing NESTOR amplification the lid couldn't provide?

**Result**: No — and the stratified view relocates the problem entirely.
Two forward-path discoveries first:
- **`service.run_forward` caches results by request hash** (temp-dir
  JSON). Internal-physics variants that don't change the request hash
  silently return the first variant's cached array — the first σz sweep
  produced five identical columns this way. Defeat the cache (fresh
  `CACHE_DIR` per variant) for any monkeypatched sensitivity study.
  (No MCMC impact: identical request ⇒ identical result there.)
- **Regime dispatch is live in every Sobol/MCMC run to date**:
  `nrp/sobol.py` never sets `disable_regime_dispatch`, so calm night
  hours (`is_night & u < 2.5 m/s`) are served by the **uncalibrated,
  receptor-independent stagnation box**, not the plume. In the Mar 13–16
  window that's **16 of 38 night hours** (22 night-windy, 34 day).

Stratified obs vs prediction (baseline posterior-mean emissions):
| stratum | NESTOR obs→pred | SY obs→pred | IB obs→pred |
|---|---|---|---|
| night-calm (box, 16 h) | **149.7 → 40.0** | 10.1 → 40.0 | 27.3 → 40.0 |
| night-windy (plume, 22 h) | 15.4 → 9.7 | 6.7 → 7.8 | 3.1 → 9.3 |
| day (plume, 34 h) | 6.6 → 1.0 | 3.3 → 11.0 | 2.0 → 2.1 |

- **NESTOR's signal is almost entirely calm-night** (obs mean 149.7 ppb
  there vs 6.6–15.4 elsewhere), and on exactly those hours the box
  predicts a flat 40 ppb at every receptor — under NESTOR 3.7×, over
  SAN YSIDRO 4×. σz variants (class shift +1/+2, σz×0.5/×0.3) by
  construction cannot touch this stratum.
- On the night-windy stratum σz does have leverage (up to 3.3× at
  σz×0.3) but overshoots SY/IB badly; and that stratum's obs are small.
  σz tuning is a second-order knob, not the fix.

**The Saturn Blvd point** (field knowledge, 2026-07-11): the known
source near NESTOR is the Tijuana River channel at the **Saturn Blvd
crossing** — and `Saturn Blvd Bridge` (channel archetype) is already in
the inventory at **0.89 km from NESTOR-BES**, the closest source to any
receptor. But the v1 box is receptor-independent, so this proximity is
*invisible on precisely the calm-night hours that dominate NESTOR's
signal*. The geometry that should explain NESTOR≫SY/IB at night is
discarded by the model component that rules those hours.

**State change**: The NESTOR under-prediction is not a plume-physics
problem (lid dead, σz second-order): **it's the uncalibrated,
geometry-blind stagnation box**. The receptor pattern on calm nights
(NESTOR 150 / IB 27 / SY 10) looks like distance-to-channel-sources —
exactly what a receptor-dependent local-emissions kernel would produce
with Saturn Blvd Bridge 0.89 km from NESTOR.

**Next**: Make the stagnation box receptor-dependent: per-receptor
`E_local` as a distance-weighted sum of source rates (e.g.
`Σ_s rate_s · exp(-d_rs/λ)`), with λ, `tau_h`, and box height as
calibratable parameters (service issue #3's planned follow-up; the "242
Berry >100 ppb hours" are the natural calibration target). Forward-sweep
λ locally first — same harness — before any MCMC.

## 2026-07-11 — lid_forward_sweep (mixing-height hypothesis killed at the physics level)

**Question**: At fixed emissions (baseline posterior means), does the
nocturnal lid actually amplify predictions during NESTOR's night hours —
i.e., could the MCMC treatment (below) have failed only because free
`obs_sigma` out-competed the lid?

**Result**: No — **the lid is essentially inert for this source–receptor
geometry**. Local forward sweep, `L_night` ∈ {None, 50, 100, 200, 400} m,
Mar 13–16 window (72 h, 38 nocturnal):
- NESTOR night-mean prediction: 22.5 ppb unbounded → 27.3 at L=50 m
  (**1.21×**), 23.0 at L=100, **1.00× at L≥200**. Needed: **3.2×**
  (night obs mean 71.9). SAN YSIDRO/IB behave the same (≤1.11×/1.32× at
  the extreme L=50, inert by L=200).
- Why: the lid only bites when σz approaches L. Nocturnal stability here
  is Pasquill D(25)/E(7)/F(6 hours) (night winds median 3.2 m/s), and
  Briggs-rural σz at receptor distances is **7–103 m** — far below even a
  200 m lid. The posterior's inability to identify `L_night` was correct:
  the likelihood is genuinely flat in it.

**State change**: The nocturnal mixing-lid hypothesis (open since
2026-05-12, motivated 5–10× amplification) is **dead as the explanation
for NESTOR's 3.4× under-prediction** — not confounded, not under-sampled;
the plume physics cannot deliver the enhancement at these σz. Do NOT
spend an MCMC on the σ-fixed lid re-run; the sweep already bounds its
effect at ≤1.2×. The missing factor of ~3 at NESTOR nights must come from
elsewhere: (a) emissions timing/magnitude at night (diel modifier shape),
(b) a missing source near NESTOR, (c) met representativeness on calm
nights (night winds down to 0.2 m/s; the logged "+125 ppb on S-wind calm
hours"), or (d) the σ-scheme itself (Briggs rural may over-dilute in
stable urban terrain — a *smaller* σz at night would raise concentrations
without any lid).

**Next**: Cheapest first: (1) forward sensitivity of NESTOR night bias to
the σz scheme (e.g., urban McElroy–Pooler or a stability-class shift
D→E/F) — same sweep harness, no MCMC; (2) check NERR (TJRTLMET) winds vs
Open-Meteo for the calm-night hours (open question since 2026-05-05);
(3) if neither closes the gap, revisit source inventory near NESTOR.

## 2026-07-10 — mixing_height_treatment (lid + per-receptor obs_sigma; negative, confounded)

**Question**: Does adding a nocturnal mixing lid (`mixing_height_night_m`,
prior U(50, 500) m, binary `is_night` regime, `L_day`=1500 m fixed) fix the
NESTOR 3.4× under-prediction — with per-receptor `obs_sigma` estimated in
the same run so coverage is meaningful? (Design:
`docs/mixing_height_experiment.md`; image `nrp-worker:2597a82`.)

**Result**: Baseline re-run (same seed/window/particles, now archived:
`runs/mcmc/…_seed42_2026-07-10/`) reproduces the mis-specification: max
Rhat 1.09, 7/11 params railing, coverage 0–7%, NESTOR obs 41 → pred 12.
Treatment (`runs/mcmc/…_seed42_mhlid_fitsig_2026-07-10/`) **converged
beautifully (max Rhat 1.004, ESS ≥3200) but for the wrong reason**:
- **`L_night` is unidentified**: posterior 280 ± 126 m, 94% HDI 79–492 —
  essentially the U(50, 500) prior returned. The plausibility gate
  (concentrate in ~50–300 m) FAILED.
- **The free noise ate the signal**: fitted `obs_sigma` = 9.3 (SAN
  YSIDRO), **89.3 (NESTOR — more than 2× the obs mean of 41)**, 17.7 (IB).
  With NESTOR's misfit absorbable as noise, the likelihood preferred
  *shrinking* emissions (`baseline_scale` 2.45→1.43, `diel_amplitude`
  9.4→6.3) over using the lid: predicted means collapsed everywhere
  (SY 16.3→4.1, NESTOR 12.2→**2.5**, IB 12.6→3.1). NESTOR bias *worsened*
  3.4×→16×; its RMSE 83.8→93.5. Coverage "improved" to 18–29% purely via
  inflated σ.
- Several formerly-railing params (substrate_alpha, substrate_threshold,
  diel_amplitude/phase) moved interior — but with posteriors ≈ priors,
  i.e. released by the noise inflation, not newly identified.

**State change**: Bundling the lid with free per-receptor `obs_sigma`
(design decision #5) was a mistake — the two changes are confounded, and
an unconstrained per-receptor σ gives a mis-specified mean model an escape
hatch: explain NESTOR as pure noise and fit nothing. We have NOT yet
tested the lid on its own; this run does not refute the mixing-height
hypothesis, it refutes the joint design. Perfect Rhat under mis-specification
is a warning sign, not a success.

**Next**: (1) Re-run the treatment with the lid ON but `obs_sigma` FIXED
at 10 (isolates the lid; one config flag). (2) If the lid then helps,
re-introduce per-receptor σ with an informative prior (e.g. HalfNormal
scaled to each receptor's obs spread) instead of flat, so it can't absorb
3× bias. (3) Sanity-check the forward path: confirm the lid actually
amplifies NESTOR's nocturnal hours at fixed emissions (one cheap forward
sweep over `L_night` ∈ {50, 100, 200, 400} before burning another MCMC).

## 2026-07-10 — mcmc_smc_calibration (first Bayesian posterior; model mis-specification confirmed)

**Question**: Can a real Bayesian MCMC over the 11 emission parameters —
not the old point-estimate calibration — produce a converged, calibrated
posterior on the Mar 13–16 2026 window, and (the decisive test) does the
dispersion model actually *fit* the observed H₂S once uncertainty is
propagated?

**Result**: The **pipeline works end-to-end on NRP** — 8 independent
single-chain SMC fits (one K8s pod per chain, `pool="nrp_heavy"` capped at
4, preemption-retry), fanned into `mcmc_aggregate` → cross-chain
diagnostics + posterior-predictive skill → durable report at
`s3://tj-calibration/runs/mcmc/2026-03-13_2026-03-16_8chains_500p_seed42_2026-07-10/`.
SMC was used because the `tijuana_dispersion` forward model is a black box
(no gradients for NUTS); priors are Sobol-informed. **The science verdict
is negative and clear:**
- **Not converged**: max Rhat 1.35 at 500 particles (500 was a deliberate
  reduction from 1000 to survive NRP node preemption; convergence suffered
  but is *secondary* to the finding below).
- **7 of 11 parameters rail against their bounds even after widening them**
  (Q10→floor, substrate_alpha/diel_amplitude/f_arch_bay→ceiling, etc.).
  Widening just moved the rail — the signature of unidentifiability.
- **Posterior-predictive fit is poor** (the decisive number). Mean 94%
  interval coverage **2.8%** (target ~94%); per-receptor corr 0.08–0.50;
  systematic bias: **NESTOR-BES (Berry) under-predicted 3.4×** (obs 41 →
  pred 12, RMSE 84), **SAN YSIDRO over-predicted 2.8×** (obs 6 → pred 16).
  `obs_sigma=10 ppb` is far too small vs RMSE 20–84, so the likelihood is
  over-confident and coverage collapses to ~0.

**State change**: We now have (a) a working, reusable Bayesian calibration
pipeline with uncertainty quantification and a durable report, and (b) a
quantified conclusion that **the current dispersion+emission model cannot
reproduce this window's concentrations** — the parameter railing is a
*symptom* of structural mis-specification, not a bounds or particle-count
problem. This corroborates standing open questions: the **NESTOR under-
prediction 3.4×** aligns with the nocturnal **mixing-height collapse**
hypothesis (unbounded vertical mixing → 5–10× under-prediction of
ground-level concentration) and the logged "+125 ppb NESTOR under-
prediction on calm S-wind hours"; the over-confident likelihood shows the
noise model needs to be realistic/estimated.

**Next**: Model-side experiments, now cheap to run through this pipeline:
(1) add a **mixing-height cap** to the forward model and re-fit — expected
to lift NESTOR predictions most; (2) **estimate `obs_sigma`** (ideally
per-receptor) instead of fixing it, so coverage is meaningful; (3) **fix
the near-inert `f_arch_*` fractions** to remove degeneracy; then re-run at
≥1000 particles once a non-preemptible/short-enough configuration is
sorted (or after an NRP priority-class request) to confirm convergence.

## 2026-06-24 — multi-window Sobol deferred; MCMC design phase begins

**Question**: Can we validate the single-window Sobol sensitivities across
6 windows (warm/cool, dry/wet seasons)?

**Result**: Multi-window bulk submission encountered repeated cluster
issues (backfill failures, incomplete chunks, port-forward instability).
Diagnostic: 3 of 6 window backfills failed; those that completed had
~97% of chunks. Infrastructure blockers outweigh the benefit of validation
at this stage.

**State change**: Sobol sensitivity results remain solid for the baseline
window (2026-03-13); deferring multi-window robustness check. Pivot to
MCMC calibration using baseline Sobol to inform parameter priors + proposal
scaling.

**Next**: Implement `mcmc_chain_results` asset. Design: sample posterior
over the 11 parameters; use Sobol ST indices to scale the proposal distribution
(high-ST parameters get tighter priors; low-ST get wider). Target: 4 chains ×
10k iterations each. Evaluate convergence (Rhat, effective N_eff) + fit quality
(LOO-CV / fold-based cross-validation).

---

## 2026-05-22 — sobol_full at N=8192 on NRP (converged variance decomposition; LHS Pearson corrected)

**Question**: variance decomposition of the 11 emission parameters
across 3 receptors × 3 fit metrics, at the design scale (N=8192,
106 496 Saltelli samples) — the first NRP-side workload graduating
from a Pearson-correlation proxy to proper Sobol indices.

**Result**: Converged (`ST_conf/|ST|` median 0.15, p90 0.26, zero
negative-S1 rows). Two clean patterns:
**(A)** *magnitude* fit (rms, peak_ratio) at every receptor is
dominated by **`substrate_threshold`** (ST ≈ 0.44, S1 ≈ 0.14 — i.e.
*interaction-dominated*; the LHS Pearson proxy systematically
underestimated it ~3×), then `baseline_scale` (ST 0.35), then `T_ref_c`
(ST 0.28). **(B)** *shape* fit (`corr__*`) is dominated by
**`diel_phase_hours`**, largely first-order (S1 0.61 → ST 0.77 at
Berry — the single largest index in the whole 11×9 table). Dead
parameter: **`f_arch_bay`** ST ≈ 5×10⁻⁶ (drop from future
calibrations); `f_arch_channel` ST 0.009 borderline. Geographic:
`f_arch_estuary` is mid-pack everywhere except IB CIVIC CTR (ST 0.36),
where the estuary outlets sit closest — Sobol localises a finding the
LHS Pearson reported as global.

**State change**: The 2026-05-05 LHS Pearson approximation said
`f_arch_estuary` was the *dominant* sensitivity (Pearson r = −0.64 vs
Berry `corr`). That was a univariate artifact: Sobol places
`f_arch_estuary` mid-pack at Berry (ST 0.12) and replaces it with
`diel_phase_hours` (ST 0.77). The substrate parameters, which the
attribution experiment found weak as solo Spearman drivers (< 0.11),
are the most influential magnitude-fit parameters globally *through
interactions* — both findings are true under their framings;
substrate is non-univariate, not unhelpful. The Q10/temperature
finding from attribution is *regime-conditional*: Sobol over the full
window dilutes it (`Q10` ST ≈ 0.04), but the attribution-on-stagnation
result stands. Future calibrations should use regime-conditional Sobol.

**Next**: (1) drop `f_arch_bay` (and consider `f_arch_channel`) from
the parameter set to 9–10 free params; (2) regime-conditional Sobol
(stagnation vs advective) at the same N to resolve the Q10/substrate
framings; (3) postmortem PR for the two NRP-run papercuts surfaced
(submit-script default of N=16 letting a smoke run masquerade as the
real one; fetcher's S3 path template assumed a non-existent run-id
segment).

---

## 2026-05-16 — event_trigger_magnitude (capstone: exogenous magnitude is unreachable)

**Question**: box→driver ranks calm nights but recall@100 = 0. Does an
episodic trigger (via the shipped #6 `substrate` multiplier hook)
recover magnitude — and is the usable trigger exogenous (forward) or
only autoregressive (nowcast)?

**Result**: 7 exogenous episodic features × 4 percentiles × 5 boosts,
Youden-J@100 train objective, same 70/30 split. **Every exogenous
trigger: held-out recall@100 = 0.00, precision = 0.00** (best train
J ≈ 0.02 — nothing fires on the right hours). The autoregressive
reference (`h2s_lag_1h`, NOT forward-usable) reaches recall ≈ 0.21,
precision ≈ 0.35, Spearman ≈ 0.45.

**State change (capstone of the whole calm-night arc)**: Berry's
>100 ppb nocturnal extremes are **not predictable from any exogenous
input in this dataset** — advection (v3→v3.6), constant box, the
temperature emission driver (ranks only), and now any exogenous
episodic trigger all fail on magnitude. The forward model's ceiling
in this regime is **ranking** (Spearman ≈0.27–0.34); **magnitude is
reachable only autoregressively** (a nowcast/persistence product, a
different class from the forward model), and even then modestly
(recall ≈0.21). The binding constraint is **data, not modelling**:
stop calibrating the forward model against Berry's extremes — that
line is exhausted.

**Next**: (1) keep the #2 guardrail + "box→driver = ranker" posture
(already correct, now fully evidence-backed); (2) if extreme
magnitude is required, scope it as a **separate persistence/nowcast
component** fed by recent observed H2S / a real-time upstream sensor,
with realistic targets (recall ≈0.2); (3) the real lever is **new
real-time/independent data** (anemometer, upstream H2S) — modelling
of `modeldata_h2s_nofill` is exhausted for this regime.

---

## 2026-05-16 — box_driver_calibration (qualified positive: ranker, not magnitude)

**Question**: service #6 shipped a temperature-led `E_local(t) =
E0·Q10^((T−T_ref)/10)` for the box. Calibrated, does the box→driver
line clear the constant-box held-out rank-skill ceiling (0.127 op /
0.218 stable_atm)?

**Result**: Yes for *ranking*, no for *magnitude*. Shipped v0.4.0
model, same chronological 70/30. Identifiability handled (box linear
in E0 → closed-form; T_ref absorbed into E0, fixed; only Q10 & τ move
held-out rank skill → amplitude-invariant rank ceiling is the decisive
stat). Driver-box held-out rank ceiling **0.271** (op) / **0.338**
(stable_atm) — clears the constant box by **+0.144 / +0.120** (~2×),
hitting attribution's ~0.33 temperature bound and the floor of the
0.3–0.5 design target. **But recall@100 = 0.00** everywhere; median
pred at >100 hrs ≈ 9–10 ppb vs ≈ 167–177 obs (~17–20× short); May
10-11 event peak 7.7 ppb (no better than the constant box's 9.2) vs
177. RMSE-optimal Q10=1.5 (bulk-dominated) vs rank-optimal Q10=5.0
(physical edge) — report the rank-optimal for the operational goal.

**State change**: The box→driver structure is **validated as a
relative calm-night severity *ranker*** (~2× the constant box, at the
predicted ceiling) but is **not** an absolute-ppb predictor in the
extreme regime and must not be shipped/reported as one. Temperature
ranking tops out ≈0.34; the gap to the autoregressive bound
(`h2s_lag_1h`≈0.70) is episodic/triggered persistence, **not**
recoverable by more emission-driver tuning (Q10 already pegged at the
physical edge). Closes the temperature-emission-driver line on a
qualified positive.

**Next**: (1) service framing — expose box→driver as a calm-night
risk *rank/percentile*, keep #2 guardrail for magnitude honesty;
(2) a *new* magnitude line — event-trigger amplitude (flow/SBIWTP
spike or h2s-persistence gate) targeting recall@100, baselined
against this run; (3) `stable_atm` into the classifier (standing rec).

---

## 2026-05-15 — emission_driver_attribution (temperature is the lever)

**Question**: box_calibration showed Berry's calm-night residual is
emission-driven. Which *exogenous* driver carries it, and does the
shipped `emissions.py` form capture it? (Bar: the constant-box
held-out rank-skill ceiling 0.127 operational / 0.218 stable_atm.)

**Result**: Held-out (same 70/30 split). **`temperature_2m` alone →
Spearman 0.33** on Berry stagnation hours, both regime definitions —
2.5×/1.5× the ceiling, monotone, physically coherent (Q10 microbial
sulfate reduction). No other single exogenous driver clears the bar;
flow/SBIWTP terms all < 0.11. **The shipped `emissions.py` form,
unfitted, FAILS: 0.02 / −0.11** — its `f_volatilization ∝ wind²`
suppresses emissions exactly on calm nights. A non-negative
multivariable blend is *worse* than temperature alone (parsimony
wins). Autoregressive `h2s_lag_1h ≈ 0.70` bounds predictability — that
gap is the persistence the box supplies endogenously.

**State change**: The next component is a **temperature-led
`E_local(t)`** (Q10 form, `E0`/`T_ref` to be calibrated), feeding the
existing box; the wind-quadratic volatilization factor must be
**excluded** from the box path (it has the wrong sign for the trapped
regime). Substrate/flow is optional/secondary. Realistic driven-box
target ≈ 0.3–0.5 Spearman, not 0.7 (box memory carries the rest).

**Next**: service-repo issue — time-varying `E_local(t)` wired from
`EmissionsModel` into the stagnation box (drafted from this
evidence); then paired experiments-repo calibration of Q10/T_ref/E0
on the box path vs the 0.127/0.218 bar.

---

## 2026-05-15 — box_calibration (negative: box necessary, not sufficient)

**Question**: service issue #3 shipped the calm-night accumulation box
+ regime dispatch with deliberately uncalibrated defaults. Does
*calibrating* it (τ, lumped E_local; H_mix table & area held at
physical defaults — amplitude is otherwise unidentifiable from one
receptor) against Berry's 242 >100 ppb hours give the calm-night
regime real skill?

**Result**: No. Chronological 70/30 split. Held-out **rank-skill
ceiling** (Spearman, amplitude-invariant → cannot be gamed by the fit)
is only **0.13** with the operational `is_stagnation` classifier and
**0.22** with `stable_atm`. recall@100 = **0.00** (lifts none of the
held-out >100 ppb hours over 100; median pred ~9–11 vs obs ~167–177
ppb). τ pegs at the 12 h grid max. Shipped-dispatch event check
(May 10–11): pure Gaussian peak 0.16 ppb → calibrated box 7.9 ppb
(~50× lift, right direction) but still ~22× short of the 177 ppb
observed. `stable_atm` again beats the wind-threshold classifier.

**State change**: The box correctly removes the *geometric* Gaussian
failure but a *constant* lumped emission modulated only by atmospheric
stability cannot select which calm nights spike — the residual
variance at Berry is **emission-driven** (upstream production: flow /
SBIWTP / temperature), not ventilation-driven. The "bare box" line is
closed the way v3.6 closed the advective line. Keep the shipped box
(structure + dispatch are correct); do **not** hard-wire these
uncalibrated τ/E_local as tuned.

**Next**: an **emission-driver term** — make the box's E_local
time-varying, coupled to the `sbiwtp_*` / `flow_*` / `temperature_2m`
/ diel proxies already in `modeldata_h2s_nofill` (an `emissions.py`
extension; design/issue, not a parameter tune). Separately:
experiments-repo `tijuana-dispersion` pin is `@v0.3.0` (predates the
box); bump to a release tag including issue #3 (PR-gated).

---

## 2026-05-15 — calm_night_wind_reanalysis (supports (b); finds a ready classifier)

**Question**: is the model's Berry-extreme miss explained by (a) an
unmodelled WNW–NNW source or (b) unreliable calm-night wind direction?
Status log said: pull an independent anemometer (NERR/TJRTLMET).

**Result**: No independent anemometer exists in the pipeline
(`data/manifest.yaml` ships only Open-Meteo; `modeldata_forecast_15min`
fetched corrupt). Ran the strongest internal-consistency reanalysis
instead:
- The dataset's own **`stable_atm` flag marks 88% of Berry's 242
  >100 ppb hours** (vs 33% baseline) and *every* May 10-11 spike hour.
- Wind direction rotates ~68° across the four >100 ppb hours (~115°
  across the surrounding calm window) at 1.5–2.5 m/s; ends the hour
  speed returns to ~5.7 m/s and `stable_atm`→0.
- Hour-to-hour |Δdir| is **4× noisier** calm-night (28.9°) than windy
  (6.8°). SY vs NESTOR Open-Meteo direction diverge **up to 52°**
  during the spike (4 km apart).
- Gust/mean ratio was **non-discriminating** (2.79 vs 2.88) — negative
  result, recorded.

**State change**:
- Explanation **(b) is well-supported**: the calm-night Open-Meteo
  wind *direction* is unreliable for plume routing. The earlier
  "river sources are downwind of Berry → predict ≈0" conclusion rests
  on a direction the data itself flags stable, that is 4× noisier and
  rotates ~68° in four hours and disagrees with the adjacent grid
  point by up to 52°. The Berry miss is **at least partly a met-input
  failure, not purely a missing source.**
- **Cannot positively confirm (a) vs (b)** without external met — the
  reanalysis shows the wind is untrustworthy, not that the SE river
  sources are the cause. Stated explicitly to avoid over-claiming.
- **A stagnation classifier already exists**: `stable_atm` (88%
  precision on >100 ppb) is better than the raw `is_night & wind<2.5`
  heuristic in service-repo guardrail PR #4 / box-model issue #3.

**Next**:
1. Add an independent anemometer (NERR TJRTLMET / SD APCD) +
   fix the corrupt `modeldata_forecast_15min` in `data/manifest.yaml`
   (PR-gated — flagged, not done). Only way to positively close (a)/(b).
2. Service repo: re-key issue #2 (guardrail) and #3 (`stagnation_box`)
   off `stable_atm` rather than a raw wind threshold.
3. Ignore wind direction when `stable_atm=1` & speed<~2.5 in any
   advective routing.

---

## 2026-05-12 — calibration_v3.6 (nocturnal mixing-lid, Tier-1) — rejected, decisive

**Question**: does a limited-mixing Gaussian lid (trap emissions under
a collapsed nocturnal boundary layer) recover Berry's calm-night
extreme regime?

**Result**: No, and the failure mode is the key finding. Lid
implemented as a per-(t,r,s) multiplicative factor on the unbounded
footprint (stays linear → reuses NNLS), `L(t)=clip(k_L·max(u,.5)·s(stab),
30,2000)`, `k_L` fitted with single-amp diel.
- Holdout Spearman: baseline (no lid) SY 0.182 / Berry 0.525 / IB
  0.473 → v3.6 (lid) 0.172 / 0.504 / 0.457. Uniformly slightly worse.
- `k_L` fitted to the weak-lid end (165) — the optimizer correctly
  reports the lid only does harm (amplifies quiet advective nights)
  with no compensating gain.
- Calm-night-extreme submetric @Berry (night & wind<3.5 & obs>50):
  obs ~179 ppb, baseline pred ~9.4, v3.6 ~9.3. No effect.

**State change** (this closes the plume-model line):
- A mixing lid scales the *advected* footprint. During Berry's
  flat-direction calm extremes the river sources are downwind →
  unbounded footprint ≈ 0 at Berry → max(1,…)·0 = 0. **You cannot
  trap a plume that never arrived.** Any footprint-scaling correction
  (diel v3, per-arch diel v3.1, more sources v3.2/v3.5, lid v3.6) is
  structurally incapable of the stagnation regime. Six experiments now
  converge on this wall.
- **Tier-2 box/accumulation model is necessary, not optional.** It
  needs a source term with no upwind advective path:
  `C[t]=C[t-1]·e^(-Δt/τ)+(E_local/(A·H_mix))·τ·(1-e^(-Δt/τ))` for
  `u<u_calm`, with a regime classifier handing off to the Gaussian
  when advection resumes. This is a new model CLASS → a service-repo
  `stagnation_box` backend (the backend protocol already exists), a
  design+PR effort, not another experiments-repo footprint tweak.
- **The v3 plume line has reached its ceiling.** Best config = v3.5
  (Berry Spearman 0.525 on the advective bulk). No further plume-side
  experiment will move the extreme regime.

**Next**:
1. Stop plume-side experiments (v3→v3.6 all agree).
2. Service-repo: scope a `stagnation_box` backend + a regime
   classifier; validate on the 242 Berry >100 ppb hours.
3. Service-repo issue (safety): until the box backend exists, the
   service should flag calm nocturnal hours as out-of-envelope rather
   than emit a confident low number when truth can be 150–750 ppb.
4. Calm-night wind reanalysis (NERR/TJRTLMET vs Open-Meteo) still
   worth doing — informs the box ventilation term + classifier
   threshold.

---

## 2026-05-12 — may1011_event_analysis (model misses a real 177 ppb event)

**Question** (user-triggered): high H₂S was reported May 10–11 ("Berry
Elementary"). Do our predictions capture it? Are the river sources
included?

**Identity correction (2026-05-15)**: `NESTOR - BES` **IS Berry
Elementary School**. An earlier draft of this entry wrongly said Berry
was absent from the data (naive substring search hit "Mulberry Dr" in
San Marcos). Berry is our primary receptor; the analysis below is
exactly the answer to the user's question — only the label was misread.

**Result**: There was a large real event at **Berry Elementary
(NESTOR-BES)**: a sharp
4-hour nocturnal spike, 171→177→171→156 ppb at 23:00 May 10 → 02:00
May 11, collapsing by 04:00. SY and IB stayed ≤ 5 ppb. The model
**misses it entirely**: predicted ≈ 1 ppb against 171–177 observed
(NESTOR Pearson 0.019 on the May 9–12 window; predicted max 22 ppb vs
observed 177).

River sources **are** included (36 of 55 sources: 18 channel 3.21 g/s,
7 drain 4.31 g/s, 11 estuary 1.46 g/s). But during the spike the wind
was FROM the WNW→NNW (288–340°) at 1.5–1.7 m/s. Bearing analysis: every
channel source (126–239°) and every drain source (134–212°) sits
*downwind* of NESTOR for that wind — 0.00 of 7.5 g/s channel+drain is
in the upwind arc. Only ~1.3 g/s (some estuary + the 2 bay ponds) is
geometrically able to reach NESTOR, yielding ~1–4 ppb.

**Generalised** (not a one-off): across Berry's full record there are
242 hours > 100 ppb — 97 % nocturnal, median wind 2.4 m/s, 74 % under
3.5 m/s, and **wind direction uniform across all 16 sectors**. Flat
direction + near-calm + nocturnal = stagnation/accumulation, NOT
directional advection. (All-time Berry max 752 ppb, 2026-04-04.)

**State change**:
- The model has **no skill on calm-night stagnation events, and this
  is structural**. A steady-state Gaussian plume (c ∝ 1/u, requires a
  meaningful wind direction) cannot represent a no-preferred-direction
  near-calm nocturnal accumulation process. The extreme regime — the
  one that matters most for health — is a different physical process
  than the model class can represent. Apr-holdout Spearman (Berry
  0.52) is carried by the advective moderate hours only. No
  source-field / diel / wind tuning fixes this; it needs a different
  model (box/accumulation conditioned on stability + mixing height),
  or the service must explicitly scope itself to non-stagnation
  conditions and flag calm nocturnal hours as out-of-envelope.
- Two explanations, (b) the more likely primary:
  (a) an unmodeled source WNW–NNW of NESTOR (coast / estuary mouth /
  South Bay), or
  (b) **calm-night wind is unreliable** (1.5 m/s nocturnal). The
  original open-questions entry flagged exactly this. Under near-calm
  down-valley drainage flow the real transport at NESTOR could be from
  the SE river sources (4–7 g/s, right there) even though the 10 m
  anemometer reports NW. Sharp onset/offset + 170 ppb under 1.5 m/s
  that vanishes when wind reaches 5 m/s is textbook nocturnal
  stagnation, not a well-mixed plume.
- **Wind-data quality is now the #1 modeling limitation**, ahead of
  source-field completeness — independently confirmed by this event
  and the SY representativeness finding.

**Next**:
1. **Calm-night wind reanalysis** (highest value): pull independent
   wind (NERR / TJRTLMET or a drainage-flow model) for May 10–11 and
   compare to the Open-Meteo NESTOR wind. NW vs down-valley SE
   disagreement would confirm explanation (b) — fix is met-data, not
   sources.
2. Add a nocturnal mixing-height / stagnation term (the long-flagged
   open question — collapsed boundary layer amplifies ground conc 5–10×).
3. Hold off on more source candidates until the wind question is
   resolved (would fit a wind artifact).
4. Berry Elementary = NESTOR-BES is already our primary receptor; no
   new monitor needed. The actionable gap is that the model misses
   Berry's calm-night events ~99% — addressed by items 1–2 above.

---

## 2026-05-12 — calibration_v3.5 (SY near-field arc) + SY ordering diagnostic

**Question**: ib_metric_reframe identified SAN YSIDRO (not IB) as the
real problem receptor (Spearman ~0.16 vs IB/NESTOR ~0.47-0.50). Is SY's
weak rank-order fit a missing near-field source (local / cross-border),
fixable by adding candidate sources around SY?

**Result**: Hypothesis rejected, but clarifying.

SY ordering diagnostic first established:
- The model under-predicts SY ~3× everywhere (obs mean 6.9 vs pred 2.2).
- Zero spike skill: SY top-decile Pearson −0.07, Spearman 0.02.
- The model predicts ≈0 in 27% of holdout hours where SY observes a
  2.5-7 ppb floor. SY's biggest uncovered regime is W/WNW wind
  (~98 hrs @ ~7 ppb; nearest modeled source 6.3 km away).
- SY-local wind diverges from NESTOR only ~7% of hours (median Δ 8°),
  so the "wrong wind" lever is weak.

v3.5 then added a 5-source near-field arc around SY (≥1.4 km, W/NW/N/E/S
covering the uncovered directions), single-amp diel:
- SY near-field absorbs only **0.19 g/s total** vs the v3.2 NE grid's
  2.48 g/s. `syW` (placed in SY's biggest uncovered regime) fits to
  **exactly zero**. NNLS demonstrably funds candidate sources when the
  data supports them (NE grid in v3.2) — it declined here.
- SY Spearman 0.165 → 0.182 (+0.018, small; likely extra DoF not a
  real source). NESTOR 0.498 → 0.525 (+0.028, genuine small gain).
  IB 0.469 → 0.473. Overfitting guard passes (nothing regressed).

**State change**:
- **SY's weakness is a representativeness limit, not a missing point
  source.** The persistent omnidirectional 2.5-7 ppb floor cannot be
  produced by any upwind point; it needs an area/background term or is
  unresolvable by a 3-receptor Gaussian-plume model at ~1 km near a
  complex urban border environment. Two independent source-addition
  experiments (v3.2 NE grid, v3.5 near-field arc) failed to lift SY
  ordering while readily lifting NESTOR's — consistent and conclusive.
- **NESTOR is the well-resolved receptor** (Spearman 0.525,
  log-Pearson 0.49). The project's success claims should be framed
  around NESTOR; SY/IB reported as met/representativeness-limited.
- **v3.5 is the marginal best overall config.** Keep it. Further
  point-source tinkering on the v3 line has hit diminishing returns.
- Improving SY is a *data* problem (co-located anemometer + area
  background / higher-res met), not a calibration problem.

**Next**:
1. Service-repo PR: make Spearman + log-Pearson first-class in the
   reported fit diagnostics (currently Pearson-only). Highest-value
   remaining work — it makes future runs report the metric that
   matters.
2. Stop point-source experiments on the v3 line (diminishing returns).
3. If SY matters operationally: instrumentation ask (SY anemometer /
   local background), not a model tweak.
4. experiments-repo issue #2 (Sobol sensitivity on NRP) for a formal
   parameter-sensitivity ranking — blocked on NRP infra.

---

## 2026-05-12 — ib_metric_reframe (IB diagnostic → project-wide metric change)

**Question**: IB CIVIC CTR's holdout Pearson r was stuck at ~0.087
across every v3.x variant. Is the model failing on IB, or is the
metric wrong?

**Result**: The metric was wrong. Three things established:

1. **IB has no independent meteorology.** Its wind columns in
   `modeldata_h2s_nofill.parquet` are byte-identical to NESTOR's
   (corr=1.000). SAN YSIDRO has its own wind; IB does not. IB also
   *leads* NESTOR by ~1 h. Both are uncorrectable data limitations.

2. **IB is heavy-tailed (median 0.5, max 130 ppb); top 3 hours = 40%
   of sum-of-squares.** Pearson r on this series is decided by ~3
   points and is not a goodness measure.

3. **Under Spearman the model is fine on IB and the whole v3 line was
   under-reported.** v3.2 holdout: IB Pearson 0.087 vs **Spearman
   0.466** (≈ NESTOR's 0.498). Across the line, IB Spearman climbs
   0.34 (v3.0) → 0.47 (v3.2) while IB Pearson stays flat ~0.08.
   NESTOR Spearman doubles 0.24 → 0.50 while its Pearson barely moves.
   **The v3.2 NE-grid breakthrough was real and large; Pearson hid it.**

**State change** (this reorders project priorities):
- **Spearman becomes the headline calibration metric** for episodic
  H₂S fits; Pearson + log-Pearson secondary. Report all three —
  ordering is receptor-dependent (Pearson flatters SY, deflates
  IB/NESTOR).
- **IB is no longer the problem receptor.** It's met-limited and the
  model already captures its ordering (~0.47 Spearman). Stop chasing
  IB.
- **SAN YSIDRO is the real problem receptor.** It is the only receptor
  where Pearson (0.20) > Spearman (0.16); its Spearman ~0.16 is far
  below IB/NESTOR (~0.47-0.50). v3.2 raised SY *magnitude* (Pearson)
  but not *ordering* (Spearman). That is the open problem.
- Every prior v3.x RESULTS.md verdict was Pearson-pessimistic. The
  canonical cross-variant scoreboard is now
  `experiments/2026-05-12_ib_metric_reframe/output/metric_comparison.csv`.

**Next**:
1. Restate the project success metric (small service-repo PR: add
   Spearman + log-Pearson to the reported fit diagnostics, currently
   Pearson-only).
2. SAN YSIDRO ordering investigation — why did v3.2 lift SY Pearson
   but not Spearman? Phase-A-style cut on SY's *non-spike* hours.
3. Backfill Spearman into the project's reporting / docs.
4. Ask the data provider whether a real IB-local anemometer feed
   exists (would raise the IB ceiling above the NESTOR-proxy limit).

---

## 2026-05-12 — autonomous-session summary (Phase A through v3.3)

For convenience: this is a roll-up of everything the autonomous Claude
Code session ran on 2026-05-11 / 2026-05-12 while @valentinedwv was on
vacation. The individual entries below carry the detail.

### State of the calibration on Apr 1-14 holdout

| Variant | SAN YSIDRO | NESTOR-BES | IB CIVIC CTR |
|---------|------:|------:|------:|
| v3 (Mar 13-15 only, original report) | (n/a) | 0.60 | 0.62 |
| v3 refit on broader windows (no NE sources)         | 0.041 | 0.201 | 0.091 |
| v3.1 (2 NE candidates, relaxed bay cap, single-amp diel) | 0.114 | 0.211 | 0.086 |
| v3.2 (12-NE-grid, single-amp diel) ← current best     | **0.200** | **0.242** | 0.087 |
| v3.3 (spill-excluded, single-amp diel)                | 0.198 | 0.218 | 0.082 |

SAN YSIDRO holdout fit improved 5× over the original v3 baseline.
NESTOR-BES climbed by 0.04. IB CIVIC CTR is the remaining problem
receptor (stuck at 0.087 regardless of every variant tried).

### Things we now believe

1. **There is a real source near (32.575, -117.040)** — directly north
   of SAN YSIDRO in the Otay Mesa industrial area. The v3.2 grid sweep
   spontaneously attributed 0.89 g/s to that cell, with 4.5 g/s total
   across the NE grid. Worth physical ground-truthing.
2. **A secondary source candidate near (32.610, -117.060)** on the
   south edge of San Diego Bay also lights up at 0.87 g/s.
3. **The bay archetype default cap (0.5 g/s) is too tight.** Otay River
   Outlet readily wants 0.9 g/s in v2-style fits. Worth a service-repo
   PR to raise the default to ~2.0.
4. **The v2-era Mar 13-15 numbers were window-specific.** v2's
   originally-reported r=0.60 (NESTOR) etc. were on a 72-hour
   spill-event window. Refit on the broader Feb-Mar window v2's r is
   0.39 / 0.15 / 0.27. Future calibration reports should default to
   holdout windows.
5. **Per-archetype-amplitude diel is a dead end.** Three experiments
   show it doesn't beat single-amp diel on holdout. Land vs water
   amplitude split is retired.
6. **Spill exclusion is a dead end.** The Mar 13-15 spill carries
   information that generalises to non-spill nocturnal regimes; v3.3
   confirms excluding it hurts holdout fit (NESTOR drops 0.02-0.04).
   The spill's signal got absorbed by *channel* sources, not Stewart's
   Drain (the documented spill source).

### Next-priority experiments (queued, not yet run)

1. **IB CIVIC CTR diagnostic** — the receptor stuck at holdout r ~0.08
   across every v3.x variant. A Phase-A-style sector decomposition for
   IB. Likely highest-leverage remaining single experiment.
2. **Refine NE grid** at 0.5 km spacing around (32.575, -117.040) and
   (32.595, -117.040). Narrows the source location further.
3. **Investigate channel-source rate inflation.** v3.3 showed channel
   sources absorb 3 g/s; this is implausibly high for 12 distributed
   "bridge / crossing" points. Either reduce the count or tighten
   bounds.
4. **Ground-truth (32.575, -117.040)** against SDAPCD industrial
   inventory, cross-border emission reports, Otay Mesa zoning.
5. Open issue: investigate physical sources colocated with NE hot
   cells (separate research task).

### Files added in this session

- `experiments/2026-05-11_calibration_v3/` — initial diel experiment
- `experiments/2026-05-11_sy_north_residual_diagnostic/` — Phase A
- `experiments/2026-05-11_calibration_v3_1/` — per-arch diel + 2 NE
- `experiments/2026-05-12_calibration_v3_2/` — 12-grid NE sweep
- `experiments/2026-05-12_calibration_v3_3_spill_exclude/` — spill exclusion

---

## 2026-05-12 — calibration_v3.3 (spill exclusion, negative result)

**Question**: Does excluding the documented Mar 13-15 spill from
training give lower drain rates and better holdout generalisation?

**Result**: No on both counts.
- Drain rates are essentially unchanged (Stewart's Drain stays at
  0.05-0.07 g/s; total drain rate 4.08 → 4.07). The hypothesis that
  the spill inflated drains was wrong: NNLS never attributed the spill
  to Stewart's Drain in the first place.
- **Channel sources** absorbed the spill's signal instead — total
  channel rate drops 3.02 → 1.81 g/s (−40%) when the spill is excluded.
  Suggests the wind direction during the spill peak hours was not
  consistent with Stewart's→NESTOR bearing, so NNLS spread the mass
  upstream onto channel sources.
- Holdout fit regresses across all three variants: NESTOR-BES r drops
  0.02-0.04. SAN YSIDRO is essentially unchanged.

**State change**:
- The hypothesis "spill inflates drain rates" is rejected.
- The Mar 13-15 spill carries information useful for non-spill
  nocturnal regimes — its inclusion improves holdout. Counter-
  intuitively, removing the most extreme event hurts generalisation.
- The "spill archetype" idea (cap 20 g/s, event-windowed activation)
  in the service repo's defaults is unmotivated by this evidence —
  NNLS doesn't even attribute the actual documented spill to its
  source.
- Channel-source rate inflation is the more worrying finding. 3 g/s
  across 12 distributed bridge/crossing points is implausibly high
  for the underlying physics — these are tagged as channel sources
  but their fitted rates approach drain magnitudes.

**Next**: Stop chasing spill exclusion. Look at IB CIVIC CTR
(stuck at r=0.08) and channel-source overfit instead.

---

## 2026-05-12 — calibration_v3.2 (NE candidate grid sweep)

**Question**: v3.1 added 2 fixed NE candidates (~1.8 g/s absorbed total)
but the SY N-residual stayed at ~12 ppb. Does a 12-cell grid sweep
across the Otay Mesa / cross-border area find a coherent source
location?

**Result**: Yes — and the spatial structure is sharp. On the Apr 1-14
holdout SAN YSIDRO r climbs from 0.115 (v3.1, 2 candidates) to 0.200
(v3.2, 12-grid + single-amp diel). Cumulative from the original v3
(no NE sources): 0.041 → 0.200, a **5× improvement on SY**.
NESTOR-BES holdout r climbs from 0.21 → 0.24 in parallel.

Fitted rates show two dominant grid cells:
- `ne11` at (32.575, -117.040) = 0.89 g/s — directly **north of SAN
  YSIDRO** by ~2 km; centred in Otay Mesa industrial zone.
- `ne30` at (32.610, -117.060) = 0.87 g/s — far NW, south edge of San
  Diego Bay.

Total NE absorption in v2-style fit: 4.51 g/s (vs 1.8 g/s with v3.1's
2 fixed candidates). NNLS spontaneously builds a coherent spatial
pattern when given freedom; this is strong evidence the source
geometry is real, not a fitting artefact.

**Side observation**: per-archetype-amplitude diel (v3.1) still does
not beat single-amp diel (v3) on holdout, even with the richer grid.
The land/water split is consistently a small holdout regression.
Stop spending time on that variant — single-amp wins.

**State change**:
- We now strongly believe there's a real H₂S source near
  (32.575, -117.040). Otay Mesa industrial / cross-border. Worth
  physical ground-truthing.
- A secondary source candidate near (32.610, -117.060) on the south
  edge of San Diego Bay also lights up.
- Per-archetype diel is *retired* as a hypothesis. Going forward,
  single global amp + phase is the canonical diel form.

**Next**:
1. Refine grid in the hot zone (25 cells at 0.5 km spacing around
   the two hot spots).
2. v3.3: spill exclusion — remove documented spill hours from
   training; check drain rate inflation.
3. v3.4: IB CIVIC CTR diagnostic. Holdout r stuck at 0.087 regardless
   of variant.
4. Ground-truth (32.575, -117.040) against SDAPCD industrial inventory
   and cross-border emission reports.

---

## 2026-05-11 — calibration_v3.1 (per-archetype diel + relaxed bay cap + candidate NE sources)

**Question**: Phase A diagnostic ([2026-05-11_sy_north_residual_diagnostic](../experiments/2026-05-11_sy_north_residual_diagnostic/))
identified two issues v3 didn't fix: the bay archetype cap was binding,
and SAN YSIDRO showed a uniquely strong N-sector signal no existing
source could explain. v3.1 changes three things at once: raise bay cap
(0.5 → 5.0 g/s), add two hypothesized NE-of-SAN-YSIDRO sources
(`northeast` archetype, cap 2.0 g/s), and split the diel amplitude into
land vs water.

**Result**: On the Apr 1-14 holdout window:
- SAN YSIDRO r: 0.041 (original v3 source field) → 0.092 (v2 fit with
  the new source field, no diel) → 0.114 (v3 single-amp diel) → 0.115
  (v3.1 per-archetype diel).
- Per-archetype diel adds essentially nothing on top of single-amp diel
  on this holdout window — the model isn't expressive enough yet for
  the land/water split to matter.
- **The dominant lift (more than doubling SY holdout r) comes from
  adding NE candidates + relaxing the bay cap** — neither of which is
  about temporal modulation. The "structural" fix dominates the
  "parametric diel" fix.

NE candidate fitted rates (v2-style, no diel): Otay Mesa Industrial S =
0.83 g/s, Otay Mesa Industrial N = 0.98 g/s. Neither hit its 2.0 cap.
NNLS spontaneously attributes ~1.8 g/s to hypothesized sources NE of
SAN YSIDRO — strong indirect evidence of a real source in that region.

The v3.1 fit hits `amp_water = 3.5` at its upper bound, signalling that
water-side sources want even stronger nocturnal amplification.

**State change**:
- We now believe there is a real source (or set of sources) NE of SAN
  YSIDRO with ~1-2 g/s combined H₂S emissions. Otay Mesa industrial
  area is the prime candidate region.
- We now believe the bay archetype default cap of 0.5 g/s in
  `tijuana_dispersion.calibration.ARCHETYPE_BOUNDS_G_S` is too tight;
  ~2.0 would be a better default (worth a service-repo PR).
- We now believe per-archetype-amplitude diel is **not** a worthwhile
  refinement until the spatial source field is more complete. The
  signal-to-noise on splitting the diel modulator is below the
  spatial-correction signal.

**Next**:
1. v3.2 — expand the NE candidate grid (6-9 sources across the Otay
   Mesa region). NNLS will reveal which locations light up.
2. v3.3 — raise `amp_water` ceiling beyond 3.5, see if performance
   keeps climbing or stabilises.
3. v3.4 — exclude the documented Mar 13-15 spill from training; check
   whether the inflated drain rates were spill-event artefacts.
4. IB CIVIC CTR–specific diagnostic — this receptor stays stuck at
   holdout r ~ 0.09 regardless of variant; needs its own work.

---

## 2026-05-11 — sy_north_residual_diagnostic (no-fitting analysis)

**Question**: Where does the SAN YSIDRO N/NE-wind residual seen in v3
come from?

**Result**: Two distinct findings. (1) The v3 NNLS hit the bay
archetype upper bound (0.5 g/s) on the Otay River Outlet bay source —
the cap is the binding constraint, not source physics. Relaxing it
should let more N-wind NESTOR signal get absorbed. (2) In the N and
NNW wind sectors, SAN YSIDRO is uniquely elevated (30 ppb mean) while
NESTOR is much lower (13 ppb) and IB sees essentially zero — opposite
to every other sector. That geometric signature requires a source
*east or north of SAN YSIDRO*, which no existing modelled source
satisfies (all sources are in the river valley, *west* of SAN YSIDRO).

**State change**:
- The v2-era diagnostic "W/SW over-prediction at SAN YSIDRO" was
  window-specific to Mar 13-15. On the broader Apr 1-14 holdout the
  *northern* residual is much larger (~12 ppb mean vs ~1.5 ppb in
  W/SW).
- The dominant fix is structural (add missing sources / relax bounds),
  not parametric (diel modulation).

**Next**: v3.1 implements both fixes simultaneously (see entry above).

---

## 2026-05-11 — calibration_v3 (diurnal modifier)

**Question**: Does adding `f_diel(t)` on emission rates fix v2's
SAN YSIDRO W/SW over-prediction and the IB CIVIC CTR magnitude/timing
mismatch identified by the sensitivity LHS?

**Result**: Partial pass. v3 fits `diel_amplitude=1.75`, `phase=4:10 am`
on Feb 1 – Mar 31, 2026; holdout on Apr 1-14. SAN YSIDRO holdout r
improves from 0.041 (v2 refit) to 0.063 (v3); NESTOR-BES from 0.201
to 0.211; IB CIVIC CTR essentially unchanged (0.091 → 0.088). However,
the W/SW residual at SAN YSIDRO — the load-bearing acceptance criterion —
grew from +1.39 to +1.76 ppb (got *worse*). Importantly, v2's
originally-reported r=0.60/0.62 numbers were on the 72-hour Mar 13-15
spill window; refit on the full Feb-Mar window v2's r is 0.39/0.15 at
NESTOR/IB. The 2-month window is a much harder fit than v2 communicated.

**State change**:
- We now believe the diel modifier was the right shape of fix for the
  v2 Mar 13-15 diagnostic but not for the *dominant* residual seen on
  a broader holdout. The Apr 1-14 SAN YSIDRO residual is dominated by
  *northern* winds where the model has zero sources and predicts ~0
  while obs is 6-30 ppb. That points to a missing source east or NE of
  SAN YSIDRO (Otay Mesa industrial? cross-border emission? local
  background?), not a temporal-modulation problem.
- We now believe v2's Mar 13-15 metrics were upper-bounded by the spill
  event boosting signal. Going forward, calibration reports must include
  holdout window numbers by default.

**Next**:
1. Investigate the SAN YSIDRO N/NE residual: identify candidate sources,
   pull weather-station data colocated with SY to verify wind reading
   isn't the issue.
2. Per-archetype diel (drain/channel vs estuary) — currently a single
   global multiplier.
3. Expand outer optimization to include Q₁₀ and substrate params.
4. Add a "background" or "Otay Mesa" source east of SY and refit.

---

## 2026-05-05 — sensitivity_lhs

**Question**: Which emissions-model parameters most influence the fit?

**Result**: 200-sample Latin Hypercube across 11 emissions parameters, evaluated on the Mar 13-15 window using the Gaussian plume backend. `f_arch_estuary` is the dominant single sensitivity (Pearson r=-0.64 against NESTOR's correlation metric). Counter-intuitively, IB CIVIC CTR's *timing* fit prefers more drain weight and less estuary weight (r=+0.30 and r=-0.35 respectively) — opposite to v2's NNLS attribution. v2 fit IB's magnitude well via estuary weight, but at the cost of phase.

**State change**: We now believe v2's estuary-heavy attribution at IB is a magnitude-driven artifact of the time-invariant model, not a real geophysical signal. The diurnal modifier is the right fix because the W-wind over-prediction at SAN YSIDRO is the same artifact in mirror image. Both stations need temporally-varying source weights to fit timing and magnitude jointly.

**Next**: Implement a diurnal modifier on emission rates (v3). Re-run on Mar 13-15 to confirm IB attribution shifts toward drains as predicted.

---

## 2026-05-05 — calibration_v2

**Question**: Does adding distributed sources (12 channel + 9 estuary grid) plus archetype-bounded NNLS materially improve fit at IB CIVIC CTR?

**Result**: Yes. r=0.07 → r=0.62 at IB CIVIC CTR. NESTOR fit slightly worse (0.60→0.56) due to physical bounds preventing v1's 40 g/s phantom rates. SAN YSIDRO regressed (0.27→0.12) due to the time-invariant model overpredicting during W-wind regimes when channel sources should have been quiet (daytime). Wind-conditional residual diagnostic surfaced this as +20 ppb over-prediction at SAN YSIDRO with W and SW winds.

**State change**: Distributed estuary sources are a real geophysical feature, not a model artifact. Time-invariant emissions cannot fit IB and SAN YSIDRO simultaneously. Bounded NNLS works (no more phantom rates) but the bounds also reveal that 11/38 sources hit their upper limit — a signal that some baseline rates need event-conditional relaxation (e.g., a "spill" archetype with cap 20 g/s, active only during documented event windows).

**Next**: This pointed to the sensitivity analysis (above) and to the diurnal modifier as v3's core addition.

---

## 2026-05-05 — demo_v1 (baseline)

**Question**: Does the dispersion service pipeline work end-to-end on real data, with reasonable physics?

**Result**: Yes. Forward Gaussian plume + naive NNLS inversion ran in ~50 ms over a 72-hour window. NESTOR fit r=0.60. SAN YSIDRO r=0.27. IB CIVIC CTR r=0.07. Several sources received unconstrained fitted rates of 30-40 g/s — physically absurd, motivating archetype bounds in v2.

**State change**: The forward physics is correct (Gaussian plume rotation, σ coefficients, ground reflection). The NNLS inversion is also correct given its inputs. The problem is upstream: insufficient sources and unconstrained rates.

**Next**: v2 (above).

---

## Open questions (not yet experiments)

These are flagged for future investigation. Don't guess; design an experiment that resolves the question.

- **Mixing height**: the current plume code assumes unbounded vertical mixing. Under nocturnal stable conditions the actual mixing height collapses to ~50-200 m, which would amplify ground-level concentrations 5-10× from the same emissions. Possible explanation for why v2's fitted rates are 100× the literature priors. *Experiment to design*: integrate a mixing-height cap into `core.py` and re-fit Mar 13-15 with literature-default rates; see if fit improves.

- **Wind data quality during calm nights**: the wind-conditional residual table for NESTOR shows +125 ppb under-prediction during "S" wind hours. Three of those hours; with mean reported wind 1.5 m/s. Calm-night anemometer readings are notoriously unrepresentative because surface eddies dominate. *Experiment to design*: pull NERR (TJRTLMET) hourly winds for the same window and compare to Open-Meteo; if NERR shows different directions, the residual is met-error, not source attribution.

- **Substrate model parameterization**: the inverse-SBIWTP form `f_substrate = 1 + α × max(0, threshold - flow)` is a placeholder. The geodemic-repo emissions model has a more developed form. *Experiment to design*: port the geodemic substrate function into the bridge hook in `emissions.py`, calibrate the rest of the parameters with substrate held to that form, and compare.
