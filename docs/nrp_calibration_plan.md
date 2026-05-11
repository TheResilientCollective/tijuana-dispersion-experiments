# Calibration with NRP — What Big Compute Enables

## The honest framing

For Gaussian-plume forward runs at our domain size, compute is not the bottleneck. The 200-sample LHS sensitivity analysis ran in 9 seconds locally; v2's NNLS calibration ran in milliseconds. Throwing 1,000 NRP cores at those exact problems would change nothing.

The right question is: **what calibration science can we do with NRP that we can't do without it?** Several real things, each delivering something the current approach can't.

## Five workloads where NRP changes what's possible

### 1. Bayesian posterior over emission parameters (high value)

Replace point-estimate calibration with proper MCMC over the ~55 emissions-model parameters. Run 8 chains × 50,000 iterations × HYSPLIT or STILT inside the forward call. ~400,000 forward evaluations at ~minute scale each = ~6,500 CPU-hours. Naturally parallelizable across chains.

Delivers: **uncertainty quantification.** Right now we have rates with no confidence intervals. The operational alert system would benefit enormously from knowing when "350 ppb predicted" comes with σ = 30 versus σ = 200. The latter is essentially a coin flip; the former is actionable.

### 2. Leave-one-event-out cross-validation with high-fidelity backend (high value)

For each documented spill or extreme event in the record (~30 events through 2024-2026), refit emission parameters excluding that event, then predict it. Quantifies how well calibration generalizes to unseen events versus overfits to the calibration set. Each fold is one full calibration run, with HYSPLIT or STILT in the loop. ~30 folds × ~100 CPU-hours each = 3,000 CPU-hours, trivially parallel.

Delivers: **honest predictive performance numbers** that hold up against agency or peer-review scrutiny. Currently we report training-set fit; that's not what regulators ask about.

### 3. Global sensitivity analysis at scale (medium value)

Sobol indices instead of the LHS+Pearson approximation we used in this session. For 11 parameters, Sobol with N=8192 base samples needs N×(D+2) = ~106,000 forward runs. With HYSPLIT in the loop that's 1,800 CPU-hours; with the Gaussian plume it's ~10 CPU-hours. Either way, feasibly parallel.

Delivers: **principled prioritization** of which parameters matter most, with proper variance decomposition. Tells us where added measurements (more pH, more sulfate, more met stations) would buy the most calibration improvement.

### 4. Synthetic event generation for alert system training (medium value)

Train the operational alert classifier on synthetic spill events spanning the regime space we don't observe enough of (high-flow + warm + spill, low-flow + cold + spill, etc.). Run forward dispersion for thousands of synthetic emission scenarios; use the synthetic concentrations as labeled training data. ~10,000 forward runs × HYSPLIT = ~150 CPU-hours. Trivially parallel.

Delivers: **alert system robustness** for rare regime combinations not present in observed data.

### 5. Real-time ensemble Kalman filter (lower priority)

Daily K8s CronJob that ingests yesterday's observations, runs an EnKF update on the emission parameter posterior, and writes the updated posterior to object storage. ~50 particles × forward evaluations × runs daily = small but persistent compute load.

Delivers: **continuously updated emission estimates** that adapt as conditions change. This is the natural endgame — the emissions model becomes a state-space model with daily Bayesian updates.

## Architecture: Railway + NRP + shared object store

Two clusters with different roles, communicating via shared persistent storage:

```
                  ┌──────────────────────────┐
   user / API ──→ │ Railway: dispersion-api  │  always-on, low-latency
                  │ - FastAPI service        │  Gaussian plume in-process
                  │ - cache layer            │  ensemble dispatcher
                  │ - submits batch jobs ────┼────┐
                  └──────────────────────────┘    │
                                                  │ (job spec via K8s API)
                                                  ▼
                                          ┌──────────────────────────┐
                                          │ NRP: dispersion-batch    │
                                          │ - Argo workflows         │
                                          │ - HYSPLIT/STILT pods     │
                                          │ - MCMC pods              │
                                          │ - results → object store │
                                          └─────────┬────────────────┘
                                                    │
       ┌────────────────────────────────────────────┘
       ▼
┌────────────────────────────┐
│ Object store               │
│ (oss.resilientservice...)  │
│ - posterior samples        │
│ - cv fold results          │
│ - sensitivity matrices     │
│ - cached forward outputs   │
└──────────┬─────────────────┘
           │
           │  Railway service reads results
           ▼
   user/API: results returned
```

Railway handles the fast path: any request that hits a cached result, or any forward run that fits in 100 ms, returns synchronously. Anything else gets dispatched to NRP, the user gets a job ID, and they poll or get notified when results land in the object store.

## Concrete first NRP workload

Don't try to deploy all five at once. The right first move is **#3, the Sobol sensitivity analysis with the Gaussian plume backend** — about 10 CPU-hours total. It's the lowest-risk way to get the K8s plumbing working: container image, job submission, result retrieval, parsing. Once that pipeline is healthy, swap in HYSPLIT for the higher-fidelity workloads.

Mechanically:

1. **Container image**: same package as Railway's, plus the Sobol sampler (`SALib` library, 5 lines). ~200 MB image, push to NRP's registry or use Docker Hub.
2. **K8s job spec**: parameterize over a chunk of the sample space; each pod runs ~1,000 samples and writes outputs to the object store. 100 pods × 1,000 samples = 100k Sobol samples, parallelism ~100×.
3. **Argo workflow**: orchestrates the 100 pods, waits for completion, fans out a final aggregator pod that pulls all chunks and computes Sobol indices.
4. **Result retrieval**: aggregator writes one parquet to `s3://.../sobol_results/{run_id}/indices.parquet`. Railway service exposes `/sensitivity/{run_id}` that fetches and returns it.

Total infrastructure to build: one Dockerfile, one Argo workflow YAML, one aggregator script. Maybe a day of work. After that, every other NRP workload follows the same pattern with different parameters.

## What this session delivered toward NRP

The sensitivity analysis we ran this session is the *prototype* of what would scale onto NRP. Same logic, ~500× the sample size, swap the backend from Gaussian plume to HYSPLIT or STILT. Code in `dispersion_service/sensitivity_analysis.py`. Output structure (`sensitivity_samples.csv`, `sensitivities.csv`) is the same shape that the NRP version would produce.

Two findings from the local 200-sample run that need NRP-scale confirmation:

1. The single strongest sensitivity is `f_arch_estuary` against NESTOR's correlation (Pearson r = -0.64). Sobol indices would tell us whether this is genuinely a first-order effect or whether it's confounded with parameter interactions.
2. For IB CIVIC CTR, lower estuary weight gives *better* timing correlation (r = -0.35) — opposite to what v2's magnitude-driven NNLS found. This is the kind of issue Bayesian calibration with proper objective weighting (timing + magnitude jointly) would resolve.

## Decisions for your check-in

Three choices that determine the NRP path. None are urgent.

1. **First workload**: Sobol sensitivity (lowest-risk plumbing test), or skip straight to MCMC (highest-value science but more complex)?
2. **Backend in the NRP forward call**: Gaussian plume (cheap, our code), or HYSPLIT (expensive, your Docker, requires NRP-side mounting of ARL met data)?
3. **Result destination**: existing `oss.resilientservice.mooo.com` bucket, or set up an NRP-native bucket (CephFS-backed S3)?

The first one is the actual decision. The other two are just where you happen to deploy.

## Bottom line

NRP changes the calibration *vocabulary*, not the calibration *speed*. With Railway alone we get fast point estimates with literature-default uncertainty. With NRP added, we get posteriors, cross-validation, sensitivity decomposition, and synthetic event corpora. The science gets better; the per-iteration time gets longer. Worth it for the operational alert system to become genuinely defensible.
