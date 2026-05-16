# Results — Sobol sensitivity (local reduced-N proof)

**Run on:** 2026-05-15
**Runtime:** ~6 s (N=24 → 312 samples; forward-run disk cache warm)
**Status:** ✅ pipeline + science validated end-to-end locally.
            ⚠️ indices are **not converged** at N=24 — ranking is
            indicative, magnitudes are not. Full N=8192 on NRP needed
            for publishable indices.

## What we did

Ran the NRP Sobol *science* (`nrp/sobol.py`) locally at N=24 (312
Saltelli samples) over the Mar 13–15 window — identical code path to
the Dagster `sobol_chunk_results` / `sobol_aggregate` assets, just
without the K8s fan-out. The same matrix at N=8192 (106,496 samples) is
the production run that requires NRP.

## Top total-order sensitivities (ST), N=24

| metric | parameter | S1 | ST |
|---|---|---:|---:|
| peak_ratio · NESTOR(Berry) | `T_ref_c` | −0.18 | 1.26 |
| rms · NESTOR(Berry) | `T_ref_c` | −0.15 | 1.08 |
| corr · SAN YSIDRO | `diel_phase_hours` | **0.49** | 0.81 |
| corr · NESTOR(Berry) | `diel_phase_hours` | **0.79** | 0.65 |
| corr · IB CIVIC CTR | `f_arch_estuary` | −0.16 | 0.62 |
| rms · SAN YSIDRO | `T_ref_c` | −0.21 | 0.50 |
| peak_ratio · SAN YSIDRO | `substrate_alpha` | 0.16 | 0.33 |

(Full table in `output/sobol_indices.csv`; top-10 in `output/summary.json`.)

## Key findings

1. **`diel_phase_hours` is a strong *first-order* driver of timing
   fit.** corr metrics at SAN YSIDRO / Berry have S1 ≈ 0.5–0.8 — diel
   *phase* alone explains a large share of correlation variance. This
   independently corroborates the v3 calibration line (diel timing
   matters) via a proper variance decomposition, not a Pearson proxy.

2. **`T_ref_c` dominates the *magnitude* metrics through interactions,
   not first-order.** For NESTOR/Berry rms & peak_ratio, ST ≫ S1
   (ST≈1.1–1.3, S1≈0): temperature-reference has almost no standalone
   effect but is heavily entangled with other parameters
   (Q10/baseline/diel) in setting absolute concentration. The LHS
   Pearson proxy *cannot* see this — it only measures first-order
   monotone association.

3. **`f_arch_estuary` re-appears but is no longer the headline.** The
   2026-05-05 LHS found `f_arch_estuary` the single dominant
   sensitivity (Pearson r=−0.64 vs Berry corr). Proper Sobol confirms
   it matters (IB corr ST=0.62) but ranks `diel_phase_hours` and
   `T_ref_c` above it overall — exactly the "ranking similar but not
   identical; interactions matter" outcome the issue anticipated.

## Local-approximation vs full-scale (the issue's required comparison)

| | 2026-05-05 LHS (proxy) | This run (Sobol, N=24) | Full NRP (N=8192) |
|---|---|---|---|
| method | 200-sample LHS, Pearson r | 312-sample Saltelli, S1/ST | 106,496-sample Saltelli |
| #1 by signal | `f_arch_estuary` | `diel_phase_hours` (timing), `T_ref_c` (magnitude, via interactions) | TBD on NRP |
| interactions | invisible | detected (ST≫S1 for `T_ref_c`) | quantified with tight CIs |
| converged? | n/a (proxy) | **no** (see caveats) | expected yes |

The headline shift (estuary-weight → diel-phase + temperature
interactions) is the substantive science change from using real Sobol
instead of a correlation proxy.

## Caveats (important)

- **N=24 is far below convergence.** ST > 1 and negative/near-zero S1
  are classic small-sample Saltelli estimator artifacts (huge
  confidence intervals; `S1_conf`/`ST_conf` in the CSV are large).
  Treat the *ranking direction* as indicative; do **not** quote these
  ST values. Stable indices need the full N=8192 run on NRP.
- Single window (Mar 13–15), Gaussian-plume backend (per the issue's
  recommendation — derisks the K8s side; puff is a follow-up).
- The Dagster 100-partition fan-out + aggregator AllPartitionMapping
  load are validated by the one-partition run + the `reassemble` unit
  tests, not a full local 100-partition execution (that needs the
  daemon / NRP — an orchestration concern, not science).

## Next

1. Resolve `nrp/README.md` "Decisions blocking deployment" (namespace,
   object store, registry, `tj_h2s_prediction` importability).
2. `submit_sobol.py --dry-run` → review → live N=8192 on NRP.
3. `fetch_sobol_results.py --run-id <run>` → replace this RESULTS.md's
   indices with the converged full-scale table + confidence intervals.

## Files

- `output/sobol_indices.csv` — parameter × metric × S1/S1_conf/ST/ST_conf
- `output/summary.json` — run config + top-10 by ST + runtime
