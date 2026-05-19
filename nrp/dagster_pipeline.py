"""
Dagster pipeline for NRP-side calibration workloads.

Asset graph:

    sobol_chunk_results (100 partitions)  ──→  sobol_aggregate
    mcmc_chain_results  (8 partitions)    ──→  mcmc_aggregate
    cv_fold_results     (~30 partitions)  ──→  cv_aggregate

Each partitioned asset materializes as a K8s Job on NRP. Asset values
persist to S3 automatically via the configured IO manager. The aggregate
assets read all upstream partitions and produce final summary parquets.

RESOURCES (see resources.py)
----------------------------
- `s3`: S3 client for reading/writing artifacts. Run artifacts land at
  s3://<bucket>/runs/<run_id>/<asset_key>/<partition_key>/...
- `slack`: two-tier webhook sender shared with the production alert system.

SLACK NOTIFICATION STRATEGY
---------------------------
Watch tier (informational):
  - Run start (`@run_failure_sensor` opposite — `@run_success_sensor` start)
  - Aggregator completion (per workload, once per batch)
  - Progress milestones on very long runs (every 25th partition)

Critical tier (actionable, requires human within hours):
  - K8s job failure that doesn't recover via Dagster's retry policy
  - Calibration regression alert: aggregator detects the new result is
    materially worse than the last committed snapshot in calibration_status

This file is a skeleton — partition asset bodies raise NotImplementedError
until the corresponding workloads are wired up. The graph structure,
resource integration, and notification policy are the substantive parts.

Read the dagster-expert skill before extending. Especially: "partitioned
assets," "io_manager," "resources," "sensors."
"""

import logging
import os
from pathlib import Path
from typing import Any

import dagster as dg
import numpy as np
import pandas as pd
from dagster import AssetExecutionContext, RunFailureSensorContext, RunStatusSensorContext
from dagster_aws.s3 import S3PickleIOManager, S3Resource
from dagster_k8s import k8s_job_executor

from . import sobol
from .resources import SlackWebhookResource

log = logging.getLogger(__name__)

#: Number of Sobol chunk partitions (fan-out width on NRP).
N_SOBOL_CHUNKS = 100


# ============================================================
# Partitions
# ============================================================

sobol_partitions = dg.StaticPartitionsDefinition([f"chunk_{i:03d}" for i in range(N_SOBOL_CHUNKS)])

mcmc_partitions = dg.StaticPartitionsDefinition([f"chain_{i:02d}" for i in range(8)])

KNOWN_EVENTS = [
    "2024_12_02_smugglers_gulch",
    "2026_02_10_stewarts_drain",
    "2026_03_14_stewarts_drain",
    # ... add events as documented
]
cv_fold_partitions = dg.StaticPartitionsDefinition(KNOWN_EVENTS)


# ============================================================
# Resource keys for K8s tag config
# ============================================================

# K8s resource hints used by op_tags below
_WORKER_K8S_TAGS = {
    "dagster-k8s/config": {
        "container_config": {
            "resources": {
                "requests": {"cpu": "500m", "memory": "1Gi"},
                "limits": {"cpu": "1", "memory": "2Gi"},
            }
        }
    }
}

_AGGREGATOR_K8S_TAGS = {
    "dagster-k8s/config": {
        "container_config": {
            "resources": {
                "requests": {"cpu": "1", "memory": "4Gi"},
                "limits": {"cpu": "2", "memory": "8Gi"},
            }
        }
    }
}


# ============================================================
# Sobol sensitivity workload
# ============================================================


class SobolConfig(dg.Config):
    """Run-time config for the Sobol workload.

    The default ``n_base_samples`` is intentionally tiny so a single
    partition materialises in seconds for local ``dagster dev`` smoke
    tests. The real full-scale value (e.g. 8192) is supplied at NRP
    submission via ``scripts/submit_sobol.py --n-base-samples``.
    """

    n_base_samples: int = 16
    seed: int = 42
    window_start: str = sobol.DEFAULT_WINDOW[0]
    window_end: str = sobol.DEFAULT_WINDOW[1]
    # Optional explicit parquet path; falls back to the repo data/ dir.
    parquet_path: str | None = None


def _parquet_path(cfg: SobolConfig) -> Path:
    return Path(cfg.parquet_path) if cfg.parquet_path else sobol.DEFAULT_PARQUET


@dg.asset(
    partitions_def=sobol_partitions,
    group_name="sobol_sensitivity",
    op_tags=_WORKER_K8S_TAGS,
    io_manager_key="s3_io",
)
def sobol_chunk_results(
    context: AssetExecutionContext, config: SobolConfig
) -> dg.MaterializeResult:
    """Evaluate this chunk's slice of the Sobol sample matrix.

    Deterministic: the full Saltelli matrix is regenerated from
    ``(n_base_samples, seed)`` and sliced by this partition's index, so
    every worker and the aggregator agree on row order without sharing
    state. The IO manager (``s3_io``) persists the return value; no
    manual S3 calls. Returns ``MaterializeResult`` so per-chunk
    observability metadata lands in the Dagster UI.
    """
    chunk_idx = int(context.partition_key.split("_")[1])
    samples = sobol.build_samples(config.n_base_samples, seed=config.seed)
    bounds = sobol.chunk_bounds(samples.shape[0], N_SOBOL_CHUNKS)
    start, end = bounds[chunk_idx]
    log.info(
        "sobol chunk %s: rows [%d, %d) of %d", context.partition_key, start, end, samples.shape[0]
    )

    if start == end:
        # Empty chunk (n_samples < N_SOBOL_CHUNKS): valid, returns no rows.
        return dg.MaterializeResult(
            value={"start": start, "end": end, "param_names": [], "metric_columns": [], "rows": []},
            metadata={"n_samples": 0, "row_start": start, "row_end": end},
        )

    df = sobol.load_window(_parquet_path(config), (config.window_start, config.window_end))
    drivers, met, _hours = sobol.make_drivers_and_met(df)
    obs = sobol.build_obs(df, _hours, sobol.RECEPTOR_NAMES)
    if not drivers:
        raise ValueError("No valid driver/met rows in the window — cannot evaluate samples.")

    problem = sobol.build_problem()
    rows: list[dict[str, float]] = []
    for global_idx in range(start, end):
        metrics = sobol.evaluate_sample(samples[global_idx], problem["names"], drivers, met, obs)
        rows.append({"_row": global_idx, **metrics})

    return dg.MaterializeResult(
        value={
            "start": start,
            "end": end,
            "param_names": problem["names"],
            "metric_columns": sobol.OUTPUT_COLUMNS,
            "rows": rows,
        },
        metadata={
            "n_samples": len(rows),
            "row_start": start,
            "row_end": end,
            "n_hours": len(drivers),
        },
    )


@dg.asset(
    group_name="sobol_sensitivity",
    op_tags=_AGGREGATOR_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"slack"},
    ins={
        "chunks": dg.AssetIn(
            "sobol_chunk_results",
            partition_mapping=dg.AllPartitionMapping(),
        )
    },
)
def sobol_aggregate(
    context: AssetExecutionContext, chunks: dict[str, dict[str, Any]]
) -> dg.MaterializeResult:
    """Reassemble all chunk outputs in sample order and run SALib Sobol.

    ``chunks`` is ``{partition_key: chunk_value}`` for every partition,
    loaded via the IO manager (local filesystem or S3 depending on env).
    The full output vector must be in the exact Saltelli row order for
    each metric column, so we place each chunk's rows at their recorded
    global indices and refuse to analyse a partial matrix.
    """
    slack: SlackWebhookResource = context.resources.slack

    asm = sobol.reassemble(chunks)
    param_names = asm["param_names"]
    problem = sobol.build_problem()
    frames: list[Any] = []
    for m in asm["metric_columns"]:
        col = asm["y_by_metric"][m]
        # SALib cannot take NaN; rms__<receptor> is NaN only when that
        # receptor lacked obs in the window (whole column NaN) — skip it.
        if np.isnan(col).any():
            log.warning("metric %s has NaNs; skipping its Sobol analysis", m)
            continue
        res = sobol.analyze(problem, col)
        res.insert(0, "metric", m)
        frames.append(res)

    indices = pd.concat(frames, ignore_index=True)
    top = indices.sort_values("ST", ascending=False).head(1).iloc[0]

    slack.watch(
        f":bar_chart: Sobol sensitivity complete (run {context.run_id[:8]})\n"
        f"Samples: {asm['n_samples']} | metrics: {len(frames)}\n"
        f"Top total-order sensitivity: {top['parameter']} "
        f"(S_T={top['ST']:.3f} on {top['metric']})"
    )

    return dg.MaterializeResult(
        value={"indices": indices.to_dict(orient="records")},
        metadata={
            "n_samples": asm["n_samples"],
            "n_metrics_analysed": len(frames),
            "n_parameters": len(param_names),
            "top_parameter": str(top["parameter"]),
            "top_ST": float(top["ST"]),
            "top_metric": str(top["metric"]),
            "indices_preview": dg.MetadataValue.md(
                indices.sort_values("ST", ascending=False).head(10).to_markdown(index=False)
            ),
        },
    )


# ============================================================
# MCMC workload (placeholder — implemented after Sobol is healthy)
# ============================================================


@dg.asset(
    partitions_def=mcmc_partitions,
    group_name="mcmc_posterior",
    op_tags=_WORKER_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
)
def mcmc_chain_results(context: AssetExecutionContext) -> dict[str, Any]:
    raise NotImplementedError("MCMC chain not yet implemented.")


@dg.asset(
    deps=[mcmc_chain_results],
    group_name="mcmc_posterior",
    op_tags=_AGGREGATOR_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3", "slack"},
)
def mcmc_aggregate(context: AssetExecutionContext) -> dict[str, Any]:
    raise NotImplementedError("MCMC aggregator not yet implemented.")


# ============================================================
# Cross-validation workload (placeholder)
# ============================================================


@dg.asset(
    partitions_def=cv_fold_partitions,
    group_name="loo_cv",
    op_tags=_WORKER_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
)
def cv_fold_results(context: AssetExecutionContext) -> dict[str, Any]:
    raise NotImplementedError("CV fold not yet implemented.")


@dg.asset(
    deps=[cv_fold_results],
    group_name="loo_cv",
    op_tags=_AGGREGATOR_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3", "slack"},
)
def cv_aggregate(context: AssetExecutionContext) -> dict[str, Any]:
    raise NotImplementedError("CV aggregator not yet implemented.")


# ============================================================
# Sensors: Slack notifications on run lifecycle
# ============================================================


@dg.run_failure_sensor(
    monitored_jobs=None,  # all jobs in this code location
    name="nrp_run_failure_to_slack",
    description="Sends critical-tier Slack message on K8s job failure.",
)
def nrp_run_failure_to_slack(context: RunFailureSensorContext) -> None:
    """Critical-tier alert — K8s pod failed and didn't recover via retry."""
    slack: SlackWebhookResource = context.resources.slack
    run = context.dagster_run
    event_data = context.failure_event.event_specific_data
    error_obj = getattr(event_data, "error", None)
    error_msg = error_obj.message if error_obj else "unknown"
    slack.critical(
        f":rotating_light: NRP run failed\n"
        f"Job: {run.job_name}\n"
        f"Run ID: {run.run_id[:8]}\n"
        f"Error: {error_msg}\n"
        f"Dagster UI: <see Dagster instance>"
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.STARTED,
    monitored_jobs=None,
    name="nrp_run_start_to_slack",
    description="Sends watch-tier Slack message when an NRP run starts.",
    minimum_interval_seconds=30,
)
def nrp_run_start_to_slack(context: RunStatusSensorContext) -> None:
    """Watch-tier announcement — informational only."""
    slack: SlackWebhookResource = context.resources.slack
    run = context.dagster_run
    slack.watch(f":rocket: NRP run started: {run.job_name} ({run.run_id[:8]})")


# ============================================================
# Definitions
# ============================================================

# Resources. If/when tj_h2s_prediction becomes pip-installable, replace
# these with imports from tj_h2s_prediction.resources and remove resources.py.
# Asset code stays the same — it only references resource keys.

defs = dg.Definitions(
    assets=[
        sobol_chunk_results,
        sobol_aggregate,
        mcmc_chain_results,
        mcmc_aggregate,
        cv_fold_results,
        cv_aggregate,
    ],
    sensors=[
        nrp_run_failure_to_slack,
        nrp_run_start_to_slack,
    ],
    resources={
        # S3 client. Configure endpoint_url for non-AWS S3-compatible stores
        # (the project's existing oss.resilientservice.mooo.com works this way).
        "s3": S3Resource(
            aws_access_key_id=dg.EnvVar("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=dg.EnvVar("AWS_SECRET_ACCESS_KEY"),
            endpoint_url=dg.EnvVar("S3_ENDPOINT_URL"),
            region_name=dg.EnvVar("AWS_DEFAULT_REGION"),
        ),
        # IO manager for asset persistence. On NRP (DAGSTER_S3_BUCKET set)
        # this is S3; locally it falls back to a filesystem IO manager so
        # `dagster dev` / `dg launch` work end-to-end without S3.
        "s3_io": (
            S3PickleIOManager(
                s3_resource=S3Resource(
                    aws_access_key_id=dg.EnvVar("AWS_ACCESS_KEY_ID"),
                    aws_secret_access_key=dg.EnvVar("AWS_SECRET_ACCESS_KEY"),
                    endpoint_url=dg.EnvVar("S3_ENDPOINT_URL"),
                ),
                s3_bucket=dg.EnvVar("DAGSTER_S3_BUCKET"),
                s3_prefix="dagster/runs",
            )
            if os.getenv("DAGSTER_S3_BUCKET")
            else dg.FilesystemIOManager(
                base_dir=os.getenv(
                    "DAGSTER_LOCAL_IO_DIR",
                    str(Path(__file__).resolve().parent.parent / ".dagster_io"),
                )
            )
        ),
        # Slack webhook sender. Reuses the same env vars as the existing
        # alert system. Optional: os.getenv with a "" default so the
        # resource initialises locally (the sender logs+drops on an empty
        # URL) instead of failing EnvVar resolution when unset.
        "slack": SlackWebhookResource(
            watch_webhook_url=os.getenv("SLACK_WEBHOOK_WATCH", ""),
            critical_webhook_url=os.getenv("SLACK_WEBHOOK_CRITICAL", ""),
        ),
    },
    # Use K8s step executor when KUBERNETES_SERVICE_HOST is set (in-cluster or
    # local dev pointing at NRP via kubeconfig). load_incluster_config is True
    # only inside a real pod (SA token present); locally it falls back to
    # ~/.kube/config so `kubectl` context determines the target cluster.
    executor=k8s_job_executor.configured(
        {
            "job_namespace": {"env": "NRP_NAMESPACE"},
            "image_pull_policy": "IfNotPresent",
            "service_account_name": "dagster-nrp",
            "max_concurrent": 100,
            "load_incluster_config": os.path.exists(
                "/var/run/secrets/kubernetes.io/serviceaccount/token"
            ),
        }
    )
    if os.getenv("KUBERNETES_SERVICE_HOST")
    else dg.multiprocess_executor,
)
