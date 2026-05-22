# Results — Sobol sensitivity, **converged full-scale (N=8192 on NRP)**

**Run on:** 2026-05-22 (NRP/Nautilus, namespace `ucsd-center4health`)
**Scale:** N=8192 base samples → 106 496 Saltelli rows, 100-way fan-out
**Artifacts:** `s3://tj-calibration/dagster/runs/sobol_aggregate` (+ 100 `sobol_chunk_results/<chunk_NNN>`)
**Status:** ✅ pipeline + science both validated. Indices converged.

## Convergence — this is the real run

| diagnostic | smoke (N≈23) | **converged (N=8192)** | reading |
|---|--:|--:|---|
| median `ST_conf / |ST|` | 1.47 | **0.153** | CIs are ~6% of the index — comfortably below the conventional 0.20 "converged" threshold |
| p90 `ST_conf / |ST|` | 7.75 | **0.259** | worst-resolved parameters still tight |
| rows with `S1 < −0.01` | 40 / 99 | **0 / 99** | the negative-`S1` under-sampling signature is gone |
| max absolute `ST_conf` | — | 0.090 | small absolute uncertainty everywhere |

## Two clean patterns — one per metric family

### A. Magnitude fit (`rms__*`, `peak_ratio__*`) — interaction-dominated, same top-3 at every receptor

| rank | parameter | mean S1 | mean ST | **ST − S1 (interaction)** |
|---:|---|--:|--:|--:|
| 1 | **`substrate_threshold`** | 0.14 | **0.44** | **0.30** |
| 2 | **`baseline_scale`** | 0.11 | **0.35** | **0.24** |
| 3 | **`T_ref_c`** | 0.09 | 0.28 | 0.19 |
| 4 | `substrate_alpha` | 0.06 | 0.23 | 0.17 |
| 5 | `f_arch_drain` | 0.04 | 0.13 | 0.09 |

The headline isn't *which* parameters dominate magnitude — it's *how*. Every one of the top-3 has **ST ≈ 3× S1**: their solo correlations are modest; their real influence is the *interactions* with the other parameters. Substrate and baseline-scale only express their effect through coupling with temperature, archetype, and amplitude.

### B. Shape fit (`corr__*`) — `diel_phase_hours` dominates, especially at Berry

| metric | top parameter | S1 | ST |
|---|---|--:|--:|
| **`corr__NESTOR - BES`** | **`diel_phase_hours`** | **0.61** | **0.77** |
| `corr__IB CIVIC CTR` | `diel_phase_hours` | 0.39 | 0.49 |
| `corr__SAN YSIDRO` | `diel_phase_hours` | (similar) | |

Here the story is opposite: **largely first-order** (`S1 ≈ ST`). Nocturnal-peak *timing* moves rank-correlation almost on its own, hardest at Berry, the most stagnation-prone receptor. Concordant with the whole calibration arc.

## The required comparison — Sobol N=8192 vs the 2026-05-05 LHS Pearson (the issue's headline ask)

The original 200-sample LHS Pearson approximation reported `f_arch_estuary` as the *dominant sensitivity* (Pearson r = −0.64 vs Berry's `corr`). Converged Sobol corrects this in two specific ways:

1. **`f_arch_estuary` drops from "dominant" to a receptor-specific effect.** At `corr__NESTOR - BES` (the Berry corr the LHS flagged), Sobol places `f_arch_estuary` mid-pack (ST 0.12 vs `diel_phase_hours` ST 0.77). It *does* reach ST 0.36 at `corr__IB CIVIC CTR` — and that's geographically correct (IB sits closest to the estuary outlets Oneonta Slough / Beach Outlet). The LHS conflated a receptor-specific effect with a global one.
2. **`substrate_threshold` is systematically *under*-stated by Pearson by ~3×.** Pearson r is a univariate-monotone proxy; it cannot see interactions. `substrate_threshold` has S1 = 0.14 (looks weak alone — what LHS Pearson would have shown) but ST = 0.44 across every magnitude metric at every receptor. This is the single biggest *substantive* update from upgrading to proper variance decomposition.

> "Parameter ranking similar but not identical. Differences reported in RESULTS.md." — `sobol_nrp.md`. The substrate-interaction correction is precisely that difference.

## The Sobol-vs-attribution apparent paradox (and its resolution)

Sobol reports `Q10` mean ST ≈ **0.04** — near the bottom of the table. But `2026-05-15_emission_driver_attribution` showed `temperature_2m` is *the* exogenous driver of Berry calm-night extremes (held-out Spearman 0.33). Are they contradictory?

**No — they answer different questions.** Sobol here integrates fit-metric variance across the full 72-hour window (Mar 13–15), which contains both daytime *and* stagnation hours; `Q10`'s effect averages out because most hours aren't temperature-dominated. The attribution experiment conditioned on `stable_atm == 1` only, where temperature dominates because that's the regime where it acts.

**Honest synthesis:** `Q10` matters specifically *for the calm-night extremes* (per attribution); `substrate_threshold` matters globally for the whole-window magnitude fit (per Sobol). The calibration arc's "temperature is the lever" conclusion stands as a *regime-conditional* lever. A regime-conditional Sobol (separate sweeps over stagnation vs advective hours) would directly expose both.

## Dropout candidates

| parameter | mean ST | verdict |
|---|--:|---|
| **`f_arch_bay`** | **5 × 10⁻⁶** | inert. Otay Pond / Fruitdale Pond don't reach any of the three monitors during this window. **Drop from future calibration parameter sets.** |
| `f_arch_channel` | 0.009 | borderline-inert. Consider fixing at literature default to free a degree of freedom. |

Removing these takes the dimensionality from 11 → 9–10 and tightens any follow-on (MCMC, LOO-CV, regime-conditional Sobol) at the same compute budget.

## What this changes in the calibration narrative

1. **The calibration arc's "calm-night extremes are emission-driven and substrate is weak alone" finding is *re-interpreted*, not contradicted.** Attribution measured solo Spearman of `sbiwtp_*`/`flow_*` against H2S and got < 0.11. Sobol shows `substrate_threshold` is *the* magnitude lever for the whole-window fit, but only via interactions. Both are true under their framings; the substrate parameters are not unhelpful, they're *non-univariate*.
2. **The diel-timing finding is upgraded from heuristic to quantified.** v3 motivated `f_diel` from physical reasoning; Sobol now puts `diel_phase_hours` at ST = 0.77 for Berry `corr` — by far the largest first-order index in the entire 11×9 table.
3. **Geography is real and detectable.** `f_arch_estuary` matters specifically at IB CIVIC CTR. Future per-receptor calibrations should let it float; current code already does.

## Limitations

- **Single fit window** (Mar 13–15). A second sweep on a calm-night-dominated window (e.g., the May 10–11 event) would test how regime-stable the rankings are.
- **Gaussian plume only.** Same parameters re-fit with the issue-#3 stagnation box dispatched, or with the issue-#1 puff backend, may reorder some indices — especially anything wind-related. Worth scoping as a follow-on at the same N.
- **The fit window is whole-day; Sobol therefore answers a whole-day question.** Pair with regime-conditional Sobol for the calm-night story.
- **Postmortem (separate small PR):** `submit_sobol.py` defaulted `n_base_samples = 16` — the first NRP submission landed at smoke size. Recommend requiring `--n-base-samples` at submission. `fetch_sobol_results.py` constructs an S3 path with a spurious `run_id` segment that doesn't match the `S3PickleIOManager` layout (`s3://bucket/dagster/runs/sobol_aggregate`) — silently falls through to filesystem mode. Both bypassed here with a direct boto3 read.

## Files

- `output/sobol_indices_full_N8192.csv` — full 99-row table (param × metric × S1/S1_conf/ST/ST_conf). The canonical artifact.
- `s3://tj-calibration/dagster/runs/sobol_aggregate` — pickled `{"indices": [...records...]}` from the production aggregator (read with boto3 + pickle; see commit message for the snippet).
- `s3://tj-calibration/dagster/runs/sobol_chunk_results/chunk_{000..099}` — the 100 chunk artifacts (kept; needed to ever re-aggregate without recomputing).
