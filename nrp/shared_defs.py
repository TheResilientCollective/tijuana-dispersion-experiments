"""Deployment plumbing shared by the two NRP code locations.

Two workspace entries / user-deployments run against the SAME Dagster
instance (one Helm release: webserver + daemon + postgres):

- ``nrp`` (module ``nrp.definitions``) — sobol / MCMC / CV / reporting,
  plain worker image.
- ``nrp-hysplit`` (module ``nrp.saturn_definitions``) — the Saturn→Nestor
  HYSPLIT workload, ``-hysplit`` image (license-gated binary baked in).

Splitting them means the HYSPLIT image is built / pinned / redeployed
without ever touching the sobol code location or its image, and a bad
HYSPLIT rollout cannot take the sobol location down (Dagster loads each
location in its own gRPC server). This module holds the pieces both
locations need — resource construction, the K8s executor, Slack lifecycle
sensors — so they stay identical by import rather than by copy.

NOTE: this module must stay import-light. It is loaded by the hysplit
location, so it must NOT import ``nrp.sobol`` / ``nrp.mcmc`` (pymc, SALib)
at module scope.
"""

import logging
import os
from pathlib import Path
from typing import Any

import dagster as dg
from dagster import RunFailureSensorContext, RunStatusSensorContext
from dagster_aws.s3 import S3PickleIOManager, S3Resource
from dagster_k8s import k8s_job_executor

from nrp.resources import SlackWebhookResource

log = logging.getLogger(__name__)


def make_resources() -> dict[str, Any]:
    """Resource dict (`s3`, `s3_io`, `slack`) used by both code locations.

    On NRP (DAGSTER_S3_BUCKET set) `s3_io` is S3; locally it falls back to
    a filesystem IO manager so `dagster dev` / `dg launch` work end-to-end
    without S3. Slack URLs default to "" (the sender logs+drops) so local
    resolution never fails on unset env vars.
    """
    return {
        # S3 client. Configure endpoint_url for non-AWS S3-compatible stores
        # (the project's existing oss.resilientservice.mooo.com works this way).
        "s3": S3Resource(
            aws_access_key_id=dg.EnvVar("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=dg.EnvVar("AWS_SECRET_ACCESS_KEY"),
            endpoint_url=dg.EnvVar("S3_ENDPOINT_URL"),
            region_name=dg.EnvVar("AWS_DEFAULT_REGION"),
        ),
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
                ),
            )
        ),
        # Slack webhook sender. Reuses the same env vars as the existing
        # alert system.
        "slack": SlackWebhookResource(
            watch_webhook_url=os.getenv("SLACK_WEBHOOK_WATCH", ""),
            critical_webhook_url=os.getenv("SLACK_WEBHOOK_CRITICAL", ""),
        ),
    }


def make_executor(max_concurrent: int) -> Any:
    """K8s step executor in-cluster, multiprocess locally.

    ``max_concurrent`` bounds concurrent step Jobs *per run* — the lever
    each location uses to stay inside the NRP pod budget (the run queue
    bounds concurrent runs across locations; see k8s/dagster-values.yaml).
    """
    if not os.getenv("KUBERNETES_SERVICE_HOST"):
        return dg.multiprocess_executor
    # load_incluster_config is True only inside a real pod (SA token
    # present); locally it falls back to ~/.kube/config so `kubectl`
    # context determines the target cluster.
    return k8s_job_executor.configured(
        {
            "job_namespace": {"env": "NRP_NAMESPACE"},
            "image_pull_policy": "IfNotPresent",
            "service_account_name": "dagster-nrp",
            "max_concurrent": max_concurrent,
            "load_incluster_config": os.path.exists(
                "/var/run/secrets/kubernetes.io/serviceaccount/token",
            ),
        },
    )


# ============================================================
# Sensors: Slack notifications on run lifecycle
# ============================================================
# Registered in BOTH code locations. `monitored_jobs=None` monitors only
# the jobs of the location the sensor is loaded in, so each location
# reports its own runs — no duplicate messages.


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
        f"Dagster UI: <see Dagster instance>",
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
