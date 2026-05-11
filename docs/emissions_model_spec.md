# River/Estuary Emissions Model — Architecture & Spec

## Why a process-based emissions model

The current calibration approach treats `E_i(t)` — emission rate at source `i` at time `t` — as a free parameter. With 38 sources and ~720 hours per month, that is 27,000 unknowns against 2,160 observations (3 receptors × 720 hours). Even with physically motivated bounds and prior shrinkage, the system is grossly underdetermined. The v2 wind-conditional residuals confirm this: the time-invariant approximation we fit produces systematic biases at SAN YSIDRO that no amount of regularization can fix without a temporal structure on emissions.

A process-based emissions model collapses that 27,000-unknown problem to maybe 30–50 physical parameters — sulfate-reduction rate constants, gas-transfer coefficients, source-specific scalars, archetype-level priors — that have meaningful units and are constrained by laboratory and field measurements from the literature. The dispersion service then becomes a validation tool: given physical parameters → computed `E_i(t)` → predicted concentrations → residual against observations. Fit the parameters, not the rates.

This is the same shift in modeling philosophy that took ground-water hydrology from "fit a transmissivity to every cell" to "fit aquifer properties and let the physics generate the field." It works when there is a real physical process to anchor.

## Physical basis (what's actually happening at each archetype)

H₂S in the Tijuana River system has two production pathways and one loss pathway that matter for our scale.

### Production (in water column / sediment)

Microbial sulfate reduction by SRB (sulfate-reducing bacteria) is the dominant source. The reaction roughly is:

```
2 CH₂O + SO₄²⁻ → 2 HCO₃⁻ + H₂S
```

Rate scales with three things: sulfate availability, labile organic carbon availability, and temperature (Q₁₀ ≈ 2–3 in the literature). Sulfate is plentiful in the marine end (estuary, bay) where seawater intrusion brings ~28 mM sulfate. It is far less plentiful in the upstream channel before sewage mixes with marine water — there sulfate comes from the sewage itself, mostly from sulfate-rich detergent residues. Labile organic carbon is what the sewage delivers; high-throughput SBIWTP operation removes most of it before discharge, so reduced SBIWTP throughput → more substrate in the channel → more H₂S production. This is the inverse-flow correlation already documented in the project memories (r = -0.47 at NESTOR-BES with one-day lag).

Sulfide-rich sediment under shallow standing water is where most production happens. The relevant area is **anaerobic submerged area**, which scales nonlinearly with channel flow: high flow flushes the channel and reduces residence time, low flow leaves stagnant pools that go anaerobic and produce H₂S.

### Volatilization (water → air)

Aqueous H₂S exists in equilibrium between H₂S(aq) and HS⁻; the pKa is ~7.0 at 25 °C. At pH 7, half the dissolved sulfide is H₂S(aq); at pH 6, ~90% is H₂S; at pH 8, ~10%. Tijuana sewage tends toward pH 7–7.5, so a meaningful fraction is volatile.

Air-water gas transfer flux is `F = k_w × [H₂S(aq)] × A`, where `k_w` is the gas transfer velocity (Wanninkhof formulation: `k_w = 0.31 × U₁₀² × (Sc/660)^(-0.5)` for low-wind regimes; switches to `k_w ∝ U₁₀^2.5` at higher winds). Wind speed at 10 m matters strongly — calm conditions reduce flux even when production is high, which causes dissolved H₂S to accumulate and then release in pulses when wind picks up. This is one mechanism for the observed nocturnal peaks: low daytime production but daytime wind suppresses release; release happens at dusk/dawn when wind is light but stable atmosphere prevents dilution.

### Loss

Atmospheric H₂S oxidizes (lifetime ~1 day in clean air, faster near pollution sources). At our timescale (1-hour transport over a few km) atmospheric loss is negligible — we treat H₂S as conservative within the dispersion footprint.

## Parameterization (what we actually fit)

Per source `i`, the emission rate at time `t`:

```
E_i(t) = E₀_i × f_T(T(t)) × f_substrate_i(t) × f_volatilization(U(t), pH) × f_diel(t) × f_arch(archetype_i) × g_i(t)
```

Where:

- `E₀_i` — source-specific baseline scalar (g/s). One per source. ~38 fitted parameters.
- `f_T(T)` — temperature ramp, Q₁₀ form: `f_T = Q₁₀^((T - T_ref)/10)`. Two fitted parameters (Q₁₀, T_ref). Bounds Q₁₀ ∈ [1.5, 3.5], T_ref typically ~20 °C.
- `f_substrate_i(t)` — substrate availability, varies by archetype.
  - **drain / channel sources**: inverse SBIWTP throughput. `f_substrate = 1 + α × max(0, Q_thresh - Q_SBIWTP(t))`. Two fitted parameters (α, Q_thresh).
  - **estuary / bay sources**: marine substrate, less variable. `f_substrate = 1 + β × marine_anomaly`. Optional, can pin to 1.0 in v3.
- `f_volatilization(U, pH)` — gas transfer factor. `f_vol = (k_w(U) / k_w_ref) × HS_fraction(pH)`. One fitted parameter for k_w intercept; pH treated as constant per archetype initially.
- `f_diel(t)` — diurnal modifier. Smooth function with two fitted parameters (amplitude, phase). The literature suggests strong nocturnal enhancement for shallow stagnant water; this captures it parametrically.
- `f_arch(archetype)` — archetype-level scalar. Five values (drain, channel, estuary, bay, spill).
- `g_i(t)` — optional per-source overrides (e.g., spill-event multipliers active only during documented spill windows).

Total fitted parameters: roughly 38 (E₀_i) + 10 (functional form constants) + 5 (archetype scalars) + spill overrides ≈ 55–60 parameters. Compared to the 27,000-unknown problem, this is tractable. Compared to v2's 38-parameter time-invariant fit, it adds 20 parameters but explains time-dependent variation that v2 cannot.

## Calibration objective

Same loss as v2 (weighted log-MSE on receptor concentrations), but the optimization variables are now the physical parameters above. The dispersion service is called inside the inner loop:

```
for trial parameters θ:
    E(t) = compute_emissions(drivers, θ)             # cheap, vectorized
    C_pred = run_forward(sources(E), receptors, met) # service call
    L(θ) = weighted_log_mse(C_pred, C_obs)
update θ to reduce L
```

The forward run is the expensive step. Caching by content hash keeps repeated calls cheap during iteration. Outer loop is a few hundred forward runs total — bounded scipy.optimize call, not a research project.

## Integration with the dispersion service

Two principles:

**The emissions model is a separate package, not a backend.** Backends compute concentration given emission rates; the emissions model computes emission rates given drivers. Mixing them creates hard dependencies and makes the emissions model harder to swap (you might want to test a process-based model against your existing geodemic-repo emissions model).

**The dispersion service stays unchanged.** It receives `SourceSpec` objects with `emission_rate_g_s` already populated. The emissions model's job is to populate those values from physical drivers before submitting to the dispersion service.

Sketch of the calling pattern:

```python
from tijuana_dispersion import run_forward, ForwardRunRequest, SourceSpec
from tijuana_emissions import EmissionsModel, EmissionDrivers

drivers = EmissionDrivers.from_dataframe(modeldata_df, hour=ts)
em = EmissionsModel(parameters=fitted_params)
sources = em.compute_sources(drivers, source_locations)  # returns list[SourceSpec]

req = ForwardRunRequest(sources=sources, receptors=receptors, meteorology=met)
result = run_forward(req)
```

## Module structure (what to build)

A second small package, `tijuana_emissions`, with:

```
tijuana_emissions/
├── __init__.py
├── drivers.py         # EmissionDrivers: T, SBIWTP, tide, wind, pH per timestep
├── functions.py       # f_T, f_substrate, f_volatilization, f_diel — pure functions
├── model.py           # EmissionsModel class: parameters → compute_sources()
├── calibration.py     # fit() against observations using dispersion service
└── parameters.py      # Pydantic schema for the parameter set; defaults from literature
```

Dependencies: numpy, pydantic, the existing `tijuana_dispersion` package. About 600–800 lines total, similar size to the dispersion package.

A skeleton is in `tijuana_dispersion/emissions.py` (this session) so the integration points are explicit. The full implementation belongs in its own package once the design is settled.

## Bridge to your geodemic-repo emissions model

You mentioned a fleshed-out emissions model already exists. The architecture above is designed to *contain* that work, not replace it. Three concrete ways to bridge:

1. **Use it as the f_substrate function.** If your existing model captures the sewage-load-to-emissions relationship better than my `1 + α × deficit` placeholder, plug it in as the `f_substrate_i(t)` callable. Same parameter-fitting machinery still works.
2. **Use it as the per-source baseline `E₀_i`.** If your model produces per-location emission rates from physical drivers without time variation, plug those values in as the baselines and let the time-varying functional form ride on top.
3. **Treat it as the truth and validate the dispersion side.** If the existing emissions model is well-calibrated independently, take its outputs as ground truth `E_i(t)`, run them through dispersion, and use the residuals to validate the dispersion physics rather than to fit emissions.

Option 1 is the cleanest integration. Option 3 is the most informative scientifically — it lets you assess each side of the chain separately rather than confounding them in a single calibration.

## Calibration workflow with this in place

End-to-end loop, once both pieces are wired:

1. Load drivers (T, SBIWTP, wind, tide) for the calibration window from `modeldata_h2s_nofill.csv`.
2. Initialize `EmissionsModel` parameters from literature priors (Q₁₀ = 2.5, etc.).
3. For each trial parameter set θ:
   a. Compute `E_i(t)` for all sources, all hours.
   b. Submit forward run to dispersion service.
   c. Compute log-MSE residual against observations.
4. Outer optimizer (scipy `minimize` with bounds) updates θ.
5. After convergence, save fitted parameter set + diagnostic plots.
6. Validate on April 1-14 holdout window (untouched during calibration).
7. Run wind-conditional residual diagnostic on holdout to detect remaining biases.

This is where v3 of the project lives.

## Open questions / decisions

Three that block full implementation, sized to fit in a check-in message:

1. **Do you want to start from scratch or port your geodemic emissions model?** If port, send me the relevant module names/functions, and I'll design the bridge. If from scratch, I'll write a clean implementation following the architecture above.
2. **Calibration window.** Confirm Feb 1 - Mar 31 2026 for fitting, Apr 1-14 for holdout? The data through Apr 17 looks clean (no flat-fill issue in the latest dataset).
3. **pH treatment.** I've assumed constant per archetype because we don't have good pH data. If you have measured pH series at any site, we can make pH a driver too; otherwise the constant-per-archetype approximation is fine and the volatilization fraction folds into the archetype scalar.

Each question is answerable in a sentence. Don't pre-decide all three; just whichever one you want to tackle first when you're back.
