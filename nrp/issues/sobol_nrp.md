# First NRP workload: Sobol sensitivity at full scale

## Why

The local 200-sample LHS sensitivity analysis (in `experiments/2026-05-05_sensitivity_lhs/`) used Pearson correlation as a sensitivity proxy. This is fast but conflates first-order effects with parameter interactions. Proper Sobol indices give us:

- **First-order (S₁)**: variance explained by varying parameter X alone.
- **Total-order (S_T)**: variance that disappears if X is held fixed.

The gap S_T − S₁ is the contribution from interactions. For 11 parameters with 8,192 base samples, Sobol needs N×(D+2) ≈ 106,000 forward runs — feasible on NRP, marginal locally.

This issue is the first workload to deploy on the National Research Platform. Beyond the science output, it's the **plumbing test** that derisks all subsequent NRP work (MCMC, leave-one-event-out CV).

## Scope

1. **Containerize the worker.** The local script at `experiments/2026-05-05_sensitivity_lhs/run.py` is the prototype. Refactor into a Dagster asset that takes a `chunk_id` partition and runs ~1,000 Sobol samples for that chunk. Each partition writes a parquet to object storage.

2. **Build the Dagster pipeline.** In `nrp/dagster_pipeline.py`:
   - Define a `static_partitions_def` with 100 chunks (`chunk_000` to `chunk_099`).
   - Define an asset `sobol_chunk_results` (partitioned) that runs the worker for one chunk.
   - Define an asset `sobol_aggregate` that depends on all partitions of `sobol_chunk_results` and produces the final Sobol indices parquet.
   - Configure the K8s executor to run `sobol_chunk_results` partitions as parallel K8s Jobs on NRP.

3. **Submission script.** `nrp/scripts/submit_sobol.py` materializes all 100 partitions of `sobol_chunk_results` (which triggers the K8s fan-out) and waits for the aggregator. Must accept `--dry-run` and `--n-samples`.

4. **Result fetcher.** `nrp/scripts/fetch_sobol_results.py` pulls the aggregator's parquet to `experiments/<this>/outputs/`.

5. **New experiment folder** `experiments/YYYY-MM-DD_sobol_full/` with `RESULTS.md` summarizing full-scale findings vs. the local 200-sample approximation.

## Acceptance criteria

- [ ] `dagster dev` shows the asset graph and partitions correctly.
- [ ] Local materialization of one partition runs end-to-end.
- [ ] Dry-run submission prints the K8s job spec without submitting.
- [ ] Live submission completes in < 1 hour wall-time on NRP with 100-pod parallelism.
- [ ] Aggregator produces a parquet with first-order and total-order Sobol indices for all 11 parameters × 9 metrics.
- [ ] Comparison to the local 200-sample LHS Pearson approximation: parameter ranking similar but not identical. Differences reported in `RESULTS.md`.

## Things to figure out

(Block deployment but not pipeline implementation — design the pipeline first, then resolve these.)

- Which NRP namespace? Which storage class?
- Object store endpoint: existing `oss.resilientservice.mooo.com`, or NRP-native CephFS-backed S3?
- Container registry: GHCR via the service repo's CI, or NRP's own registry?
- Whether to use the Gaussian plume backend (fast, locally-runnable) or the puff backend (more realistic but slower) for this first workload. **Recommendation: Gaussian plume.** Derisks the K8s side; puff workload becomes a follow-up after the puff backend is implemented.

## Out of scope for this issue

- Bayesian MCMC posteriors (separate issue).
- Cross-validation folds (separate issue).
- HYSPLIT in the loop (later, after Sobol with Gaussian plume is working).

## Estimated effort

3-5 days, mostly on the K8s and Dagster-K8s integration. The science part is identical to the local prototype.

## Reading order before starting

1. The `dagster-expert` skill — partitioned assets and K8s execution patterns.
2. `nrp/README.md` — orchestration overview.
3. `experiments/2026-05-05_sensitivity_lhs/run.py` — the prototype to refactor.
4. `docs/nrp_calibration_plan.md` — strategic context.
