# Emissions Research

The H₂S emissions model lives in this repo (not the service repo) because it's still under research.

## Why here, not in `tijuana-dispersion`

The dispersion physics is settled enough to ship: Gaussian plume, Pasquill stability, Briggs σ. The emissions model is not. We don't yet have:

- A validated parameterization for the temperature dependence of sulfate-reducing bacterial activity.
- A defensible quantification of substrate (sewage) limitation.
- A diurnal modifier that explains the observed 98%-nocturnal-extreme pattern.
- A spill-event archetype that's distinguishable from baseline drain emissions.

Until those are pinned down, the emissions model is an active research artifact, not a stable interface. Pulling it through `tijuana-dispersion`'s release cadence would either lock in immature parameters or force constant minor-version bumps.

When the model stabilizes, it migrates back into the service repo as `tijuana_dispersion.emissions`.

## Structure

```
emissions_research/
├── README.md
├── tijuana_emissions/        # the package (depends on tijuana-dispersion)
│   ├── __init__.py
│   ├── drivers.py            # EmissionDrivers
│   ├── parameters.py         # EmissionParameters, archetype defaults
│   ├── functions.py          # f_temperature, f_substrate, f_volatilization, f_diel
│   ├── model.py              # EmissionsModel, SourceSpecLocation
│   └── overrides.py          # make_emissions_model_with_overrides
├── notes/                    # design notes, derivations, references
└── tests/                    # unit tests for the package
```

## Installing

Already part of this repo's `pyproject.toml`. After `uv sync`:

```python
from tijuana_emissions import EmissionsModel, EmissionParameters

params = EmissionParameters()  # archetype defaults
model = EmissionsModel(params)
```

## Parameter archetypes

The current parameterization assumes four archetypes — drain, channel, estuary, bay — each with its own emission rate prior, upper bound, and parameter sensitivities. Defaults live in `parameters.py`:

| Archetype | Prior (g/s) | Upper bound (g/s) |
|---|---|---|
| drain | 1.0 | 5.0 |
| channel | 0.3 | 2.0 |
| estuary | 0.5 | 3.0 |
| bay | 0.05 | 0.5 |

Bounds were established by calibration v2 to keep NNLS from producing physically absurd rates (the unconstrained inversion produced 40 g/s estimates).

## Parametric forms

The emission model couples physical drivers to a per-source rate via:

```
E_i(t) = E0_i × f_arch(archetype_i)
       × f_temperature(T(t), Q10)
       × f_substrate(SBIWTP_throughput(t), substrate_α, threshold)
       × f_volatilization(wind_speed(t), water_temp(t))
       × f_diel(t, diel_amplitude, diel_phase_hours)
```

Each `f_*` is in `functions.py` with its own parameters. The intent is for a calibration run to fit `E0_i` plus the parameters of each `f_*` jointly, not to treat them as fixed.

## Status

- Forward model: done. Can take `EmissionDrivers` (a time series of T, SBIWTP, wind, etc.) and produce per-source emission rates.
- Calibration of parameters: in progress. v2 calibrated `E0_i` only; v3 (open issue) adds the parametric coefficients.
- Validation against held-out data: not yet done. Apr 1-14 is the planned holdout window.

## Open questions

1. Is the diurnal modifier per-archetype or global? (Current default: global, single phase. Sensitivity analysis suggests this needs revisiting.)
2. Should spill events be a separate archetype with elevated cap, or handled by allowing `E0_i` to be time-varying?
3. How does the volatilization term (gas exchange across water surface) interact with measured wind speed, given that the wind sensor is downwind of the source?

## See also

- Calibration v3 issue: `../experiments/issues/calibration_v3.md`.
- Sensitivity analysis results: `../experiments/2026-05-05_sensitivity_lhs/RESULTS.md`.
- Calibration log: `../experiments/CALIBRATION_LOG.md`.
