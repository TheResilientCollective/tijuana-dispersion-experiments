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
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext, RunFailureSensorContext, RunStatusSensorContext
from dagster_aws.s3 import S3PickleIOManager, S3Resource
from dagster_k8s import k8s_job_executor

from .resources import SlackWebhookResource

log = logging.getLogger(__name__)


# ============================================================
# Partitions
# ============================================================

sobol_partitions = dg.StaticPartitionsDefinition([f"chunk_{i:03d}" for i in range(100)])

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


@dg.asset(
    partitions_def=sobol_partitions,
    group_name="sobol_sensitivity",
    op_tags=_WORKER_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
)
def sobol_chunk_results(context: AssetExecutionContext) -> dict[str, Any]:
    """One chunk of Sobol samples, ~1,000 forward-model evaluations.

    The IO manager (`s3_io`) handles persistence — return value lands at
    s3://<bucket>/runs/<run_id>/sobol_chunk_results/<partition_key>.pkl
    No manual `put_object` calls needed.
    """
    chunk_id = context.partition_key
    log.info("running sobol chunk: %s", chunk_id)

    # === implementation goes here ===
    # 1. Pull Sobol sample matrix slice for this chunk
    # 2. For each sample row, evaluate the forward model via tijuana_dispersion
    # 3. Compute per-sample fit metrics (RMS, corr, peak ratio per receptor)
    # 4. Return a dict (or pyarrow Table) — IO manager handles the write

    raise NotImplementedError(
        "Sobol chunk worker not yet implemented. See nrp/issues/sobol_nrp.md."
    )


@dg.asset(
    deps=[sobol_chunk_results],
    group_name="sobol_sensitivity",
    op_tags=_AGGREGATOR_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3", "slack"},
)
def sobol_aggregate(context: AssetExecutionContext) -> dict[str, Any]:
    """Combine all Sobol chunk parquets and compute first-order + total Sobol indices.

    Reads every partition of sobol_chunk_results from S3, concatenates,
    runs SALib's Sobol analysis, writes the indices parquet. On completion,
    sends a watch-tier Slack message with the result location and top
    sensitivities.
    """
    slack: SlackWebhookResource = context.resources.slack

    # === implementation goes here ===
    # 1. Load all partition outputs (Dagster's IO manager handles this)
    # 2. Run SALib Sobol analysis
    # 3. Persist indices

    # Notify on completion (watch tier — informational)
    slack.watch(
        f":bar_chart: Sobol sensitivity complete (run {context.run_id[:8]})\n"
        f"Top sensitivity: f_arch_estuary (S_T = TBD)\n"
        f"Results: s3://<bucket>/runs/{context.run_id}/sobol_aggregate/"
    )

    raise NotImplementedError("Sobol aggregator not yet implemented. See nrp/issues/sobol_nrp.md.")


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
        # IO manager for asset persistence — all assets with `io_manager_key="s3_io"`
        # automatically read/write through this.
        "s3_io": S3PickleIOManager(
            s3_resource=S3Resource(
                aws_access_key_id=dg.EnvVar("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=dg.EnvVar("AWS_SECRET_ACCESS_KEY"),
                endpoint_url=dg.EnvVar("S3_ENDPOINT_URL"),
            ),
            s3_bucket=dg.EnvVar("DAGSTER_S3_BUCKET"),
            s3_prefix="dagster/runs",
        ),
        # Slack webhook sender. Reuses the same env vars as the existing alert system.
        "slack": SlackWebhookResource(
            watch_webhook_url=dg.EnvVar("SLACK_WEBHOOK_WATCH"),
            critical_webhook_url=dg.EnvVar("SLACK_WEBHOOK_CRITICAL"),
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
