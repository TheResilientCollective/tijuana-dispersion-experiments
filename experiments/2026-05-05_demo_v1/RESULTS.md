# Demo Run — Mar 13-15, 2026 (Stewart's Drain Spill Window)

## Setup

The demo exercises the full dispersion service pipeline end-to-end on real data covering the documented Stewart's Drain spill of March 14-15, 2026. Window is 72 hours starting March 13 00:00 PST. Three receptors (SAN YSIDRO, NESTOR-BES, IB CIVIC CTR) and 17 named source locations from `emission_sources.json`. Hourly meteorology drawn from the NESTOR-BES row of `modeldata_h2s_nofill.csv`. The demo runs three steps: forward model with seed emission rates, NNLS inversion to fit rates to observations, forward model again with fitted rates for verification.

## Aggregate numbers

| Metric | Seed run | Fitted run | Observed |
|---|---|---|---|
| Max concentration (any station) | 22.6 ppb | 338.7 ppb | 394.0 ppb |
| Forward-run wall time | 57 ms | ~50 ms | n/a |
| NNLS residual RMS | n/a | 45.6 ppb | n/a |

Per-station correlation (predicted vs observed, fitted rates):

| Station | r | Comment |
|---|---|---|
| NESTOR-BES | 0.60 | Strong fit; all three nightly peaks captured with correct timing |
| SAN YSIDRO | 0.27 | Spurious peaks; geometry attribution issues |
| IB CIVIC CTR | 0.07 | Fit captures magnitude envelope but timing is off |

## What the diagnostic plot shows

NESTOR-BES tracks remarkably well — the inversion finds an emission combination that produces all three observed nighttime peaks (Mar 13 ~13:00 PST, Mar 14 ~13:00, Mar 15 ~14:00) with correct timing and roughly correct magnitude. This validates that the forward model and the meteorology are physically connected to the dominant signal at the central station.

SAN YSIDRO shows a different story. The fitted predictions include large spurious peaks (notably around Mar 13 18:00 PST) that have no counterpart in the observations. The mechanism is identifiability: with 17 candidate sources and only 3 receptors, multiple emission distributions can explain NESTOR's signal equally well, and NNLS picks one that happens to also project a phantom plume toward SAN YSIDRO under certain wind conditions.

IB CIVIC CTR is the most informative diagnostic. The fitted predictions oscillate around the observations but cannot consistently match phase. The IB Civic Center sensor sits 3-4 km west of the dominant source cluster, beyond the reliable reach of point sources placed along the river channel. The signal there is plausibly being driven by estuary mudflat emissions and nearshore bay sources that are not in the current source list.

## Inversion artifacts

The fitted emission rates show two suspicious patterns. First, several sources got pushed to very high rates (Hollister St PS at 32 g/s, Goat Canyon PS at 40 g/s) that are physically implausible — these are in g/s of pure H₂S, equivalent to multi-kilogram daily emissions from a single point. Second, several sources hit zero (Saturn Blvd Bridge, Hollister Bridge S, Beach Outlet, CDLP W). The L1 shrinkage at λ=0.5 is doing some pruning but not enough to enforce physical bounds.

This is exactly the failure mode the formal calibration plan needs to address. The fix is not more data — it is stronger physical priors: archetype-specific upper bounds on rates, hierarchical pooling within archetypes (drains share a common rate distribution, estuary sources share another), and explicit emission parameterization where rate depends on flow and temperature rather than being a free parameter per hour.

## What this rough run validates

The pipeline is correct end-to-end: data loading, meteorological projection, geometry, dispersion physics, observation matching, NNLS inversion, and result serialization all work. Cache hits return identical results in under 5 ms. Forward runs scale linearly with time × receptors × sources and complete in under 100 ms for the demo size. The service contract is the right level of abstraction — nothing in the JSON envelope feels awkward or contrived.

The pipeline also confirms three things that motivate the formal calibration plan:

1. **Distributed sources are needed.** The fixed 17-point source field cannot explain IB Civic Center observations no matter how the rates are tuned. Channel-distributed sources between Stewart's and the beach outlet, plus estuary area sources, are required.
2. **Physical priors are essential.** Unconstrained NNLS finds physically absurd rate combinations that fit the observations equally well. Archetype-based parameterization and bounds (rate ≤ X g/s for drain archetype, etc.) are not optional.
3. **Three receptors is genuinely under-determined.** The inversion is solving for 17 unknowns from 3 sensors × 72 hours. Even with regularization, parameter identifiability is the bottleneck. Including hourly observations as separate constraints helps, but the spatial sparsity remains the fundamental limit. This argues for hierarchical models that constrain similar sources to share parameters.

## Next experiments (when calibration begins)

These are easy follow-ups that run in seconds each on the existing service:

- **Single-source attribution sweep.** For each of the 17 sources, run forward with that source alone at 1 g/s and look at which receptor lights up. This produces a 17×3 attribution matrix that diagnoses identifiability before any fitting.
- **Distributed channel test.** Add 12 distributed channel sources between Stewart's and the beach outlet, re-run inversion, see whether IB CIVIC CTR fit improves.
- **Wind-direction conditional residuals.** Bin observations by wind sector at each receptor; compute mean residual per sector. Systematic over- or under-prediction in a sector points at missing sources in that direction.
- **HYSPLIT comparison on one event.** When the HYSPLIT backend is wired, run the Mar 14 13:00 peak with both backends. Compare. If they agree on where the plume goes, Gaussian plume is good enough for the calibration loop.

All four can be expressed as one or two service calls each.

## Files produced

- `demo_artifacts.json` — fitted rates, residual RMS, summary statistics
- `demo_timeseries.csv` — observed, seed-predicted, fitted-predicted concentrations per hour per station
- `demo_timeseries.png` — three-panel diagnostic plot
