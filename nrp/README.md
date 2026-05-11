# NRP Orchestration via Dagster

Compute-rich calibration workloads that don't fit on Railway run on the National Research Platform (NRP). This directory holds the Dagster-based orchestration: pipeline definitions, the worker container image, K8s manifests for batch jobs, and submission/retrieval scripts.

## Why Dagster (not Argo)

The earlier draft of this plan used Argo Workflows. We switched to Dagster because:

- The wider geodemic project is already on Dagster — engineers and analysts know it.
- The `dagster-expert` skill from `dagster-io/skills` is installed in this repo and gives Claude Code first-class guidance for asset patterns, partitions, sensors, and K8s execution. **Read it before writing pipeline code.**
- Dagster's asset model maps better to "compute these per-(date, parameter) outputs and cache them" — which is what calibration runs actually look like — than Argo's task-DAG model.
- The Dagster UI gives the dependency graph, run history, and lineage for free.

## Structure

```
nrp/
├── README.md              # this file
├── Dockerfile             # the worker image — service package + analysis tools
├── dagster_pipeline.py    # asset definitions and job configs
├── workspace.yaml         # Dagster project config
├── k8s/
│   ├── job_template.yaml  # template Dagster fills for each K8s submission
│   └── kustomization.yaml
└── scripts/
    ├── submit_sobol.py    # submit a Sobol sensitivity run
    └── fetch_results.py   # pull results from object storage to local
```

## How it runs

1. **Local development.** From this directory: `dagster dev`. Opens the UI at http://localhost:3000 with the asset graph. Materialize individual assets locally for testing — Dagster runs them in-process against the same Python code that runs in pods.

2. **Submitting to NRP.** Once an asset materializes correctly locally, the `nrp_executor` (configured in `workspace.yaml`) routes execution to a Kubernetes Job on NRP. The pod runs the worker image, executes the asset's compute function, writes outputs to the object store, and exits.

3. **Fan-out for parallel workloads.** Sensitivity sweeps and MCMC chains are modeled as **partitioned assets** — one partition per Sobol sample chunk, one per MCMC chain. Dagster fans them out as parallel K8s jobs and aggregates results into a downstream rollup asset. The `dagster-expert` skill covers this under "partitioned assets."

4. **Result retrieval.** Each pod writes to `s3://<bucket>/runs/<run_id>/<asset_key>/`. The Dagster UI shows the location; `scripts/fetch_results.py` pulls them to local for analysis.

## Workloads, in priority order

1. **Sobol sensitivity at full scale.** ~100,000 samples × Gaussian plume. ~10 CPU-hours. The pipeline-plumbing test that derisks all subsequent workloads. See the corresponding open issue.

2. **Leave-one-event-out cross-validation.** ~30 spill events × full calibration each. ~30 CPU-hours with Gaussian plume; ~3,000 with HYSPLIT.

3. **Bayesian MCMC over emission parameters.** 8 chains × 50,000 iterations × HYSPLIT. ~6,500 CPU-hours. The big one — wait until pipeline is healthy.

4. **Synthetic event corpus.** Forward dispersion for 10,000 hypothetical scenarios. ~150 CPU-hours.

5. **Daily ensemble Kalman filter.** Scheduled (Dagster sensor or schedule). Small per-run cost; persistent.

## Container image conventions

The worker image (`Dockerfile` here) bakes in:

- `tijuana-dispersion` (pinned commit/tag from `pyproject.toml`)
- `dagster`, `dagster-k8s`
- `SALib` for Sobol/Morris sampling
- `numpy`, `scipy`, `pandas`, `pyarrow`, `matplotlib`

Tag and push from the experiments-repo CI to `ghcr.io/theresilientcollective/tijuana-dispersion-nrp:<sha>` (or NRP-native registry — TBD). Pin to the specific digest in `dagster_pipeline.py`, never `:latest`.

## Submission rules

- Every submission script accepts `--dry-run`. The first call to a new workload is always `--dry-run`. A 100,000-sample sweep costs real money.
- Every K8s job mounts kubeconfig and secrets via Kubernetes secret references, never env vars in the spec.
- Every pod tags with `project=tijuana-dispersion-experiments` and `workload=<name>` for cost accounting.
- The repo's CI does NOT auto-submit NRP workloads. Submission is always a deliberate human action.

## Resources & integration with `tj_h2s_prediction`

Two Dagster resources are wired in (see `resources.py` and `dagster_pipeline.py`):

- **`s3`** — `S3Resource` + `S3PickleIOManager` from `dagster-aws`. All partitioned asset outputs persist to S3 automatically via the IO manager, at `s3://<bucket>/dagster/runs/<run_id>/<asset_key>/<partition>.pkl`. No manual `put_object` calls in asset bodies.
- **`slack`** — two-tier webhook sender (`watch` / `critical`) matching the existing production alert system. Reuses `SLACK_WEBHOOK_WATCH` and `SLACK_WEBHOOK_CRITICAL` env vars.

If `tj_h2s_prediction` is pip-installable, the cleanest wiring is to delete `nrp/resources.py` and import its resources directly:

```python
from tj_h2s_prediction.resources import s3_resource, slack_resource
```

Asset code references resources by key (`s3`, `slack`), so swapping the source doesn't touch any asset bodies. Until that's confirmed, the inline definitions in `resources.py` work standalone.

## Slack notification policy

Lifecycle notifications are wired via Dagster sensors (`nrp_run_start_to_slack`, `nrp_run_failure_to_slack`) and aggregator-asset bodies. The deliberate split:

| Trigger | Tier | Reason |
|---|---|---|
| Run start | watch | informational, batched-friendly |
| Aggregator completion | watch | once per ~10-CPU-hour batch; includes top sensitivities or fit metrics |
| K8s job failure (post-retry) | critical | needs human within hours; pipeline is broken |
| Calibration regression > 0.2 r vs last snapshot | critical | invalidates prior results |
| Per-partition completion | (silent) | Dagster UI shows progress; would spam Slack |
| Intermediate writes | (silent) | same |

Asset bodies that need to send Slack messages declare `required_resource_keys={"slack"}` and call `context.resources.slack.watch(...)` or `.critical(...)`.

## Required environment variables

```
# S3 (existing project's bucket — `oss.resilientservice.mooo.com` or AWS)
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION         # e.g. us-west-2; required even for non-AWS S3-compatible
S3_ENDPOINT_URL            # https://oss.resilientservice.mooo.com (or empty for AWS)
DAGSTER_S3_BUCKET          # bucket name where Dagster persists asset values

# Slack (reused from the existing alert system)
SLACK_WEBHOOK_WATCH        # 30 ppb tier — informational
SLACK_WEBHOOK_CRITICAL     # 100 ppb tier — actionable

# K8s
NRP_NAMESPACE              # which namespace Dagster submits jobs into
```

These are configured as Kubernetes secrets on NRP and as Dagster instance config locally. Never committed to source.

## Decisions blocking deployment

These need answers before the first NRP submission. None are urgent — figure them out at first deployment.

1. **NRP namespace and storage class.** Which Kubernetes namespace? What storage class for PVCs?
2. **Object store.** Existing `oss.resilientservice.mooo.com`, or NRP-native CephFS-backed S3?
3. **Container registry.** GHCR via experiments-repo CI, or NRP's registry?
4. **Met data location** (when HYSPLIT enters the loop). Mounted volume on every pod, or fetched per-run from object storage?

## Result fetchers

Every workload has a paired result fetcher in `scripts/fetch_<workload>_results.py` that:

1. Reads the run's manifest from object storage (run ID supplied via CLI arg).
2. Downloads aggregated summary parquets.
3. Writes them to `experiments/<dated-folder>/outputs/`.
4. Updates `docs/calibration_status.md` with a new entry.

## See also

- Calibration history: `../docs/calibration_status.md`
- Calibration plan with NRP context: `../docs/nrp_calibration_plan.md`
- The `dagster-expert` skill: documents the canonical asset/partition/sensor patterns. **Read this before writing new pipeline code.**
