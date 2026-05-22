# Sobol sensitivity — full workload (issue #2)

**Date:** 2026-05-15
**Status:** pipeline done + locally validated; full-scale run pending NRP
**Author:** autonomous (Claude Code session)
**Issue:** experiments-repo #2 · design doc `nrp/issues/sobol_nrp.md`

## Question

Proper Sobol indices (first-order S1, total-order ST) for the 11
emission parameters across the 9 fit metrics — replacing the
2026-05-05 LHS *Pearson proxy*, which conflates first-order effects
with interactions. This is also the **first NRP workload** and the
plumbing test that derisks MCMC / LOO-CV.

## What was built

- **`nrp/sobol.py`** — framework-agnostic science: SALib problem (11
  params), deterministic Saltelli sampling, chunking, real-data loader
  (raises, never fabricates — AGENTS.md), `evaluate_sample` (reuses the
  published `tijuana_dispersion` forward model), `reassemble`, `analyze`.
- **`nrp/dagster_pipeline.py`** — `sobol_chunk_results` (100-partition
  fan-out, `SobolConfig`, `MaterializeResult` + metadata) and
  `sobol_aggregate` (`AllPartitionMapping` load → reassemble → SALib →
  Slack watch-tier + indices). `defs` made env-adaptive: local
  filesystem IO manager + multiprocess executor when NRP env is absent,
  S3 + k8s_job_executor when present.
- **`nrp/scripts/submit_sobol.py`** (`--dry-run` first, `--n-base-samples`)
  and **`nrp/scripts/fetch_sobol_results.py`** (`--dry-run`, S3 or
  local).
- **`tests/test_sobol.py`** — 11 tests: sampling determinism + bounds,
  chunk coverage, reassembly guard (rejects partial matrices), SALib
  shape, and a real-data integration check.

## Local validation (done)

- `dg list defs` shows the asset graph + 100 partitions.
- One partition materialised end-to-end (`dg launch --assets
  sobol_chunk_results --partition chunk_000`) → RUN_SUCCESS, real data,
  real forward model, filesystem IO manager.
- `submit_sobol.py --dry-run --n-base-samples 8192` → 106,496 samples /
  100 chunks ≈ 1,065 rows/chunk (matches the issue's ~1,000).
- This folder's `run.py` ran a real reduced-N Sobol (N=24 → 312
  samples) end-to-end via the pure helpers — see RESULTS.md.

## Not done here (genuinely blocked / out of scope)

- Full-scale N=8192 (~106k samples, ~10 CPU-h) — needs NRP.
- The 100-pod K8s fan-out, the Dagster daemon backfill, and the open
  infra decisions in `nrp/README.md` (namespace, object store,
  registry, `tj_h2s_prediction` importability).

## Reproduce

```bash
uv sync --extra dev --extra service
python scripts/fetch_data.py --only modeldata_h2s_nofill
# local proof (minutes):
uv run python experiments/2026-05-15_sobol_full/run.py --n-base 24
# one Dagster partition:
uv run dg launch --assets sobol_chunk_results --partition chunk_000
# submission plan (no spend):
uv run python nrp/scripts/submit_sobol.py --dry-run --n-base-samples 8192
```
