"""Standalone code location for the Saturn→Nestor HYSPLIT workload.

Deployed as its own workspace entry / user-deployment (``nrp-hysplit``,
see ``k8s/dagster-values.yaml``) pinned to the ``-hysplit`` worker image,
so the HYSPLIT workload runs and redeploys without touching the sobol
code location (``nrp.definitions``) or repointing its image. Shares the
Dagster instance (webserver, daemon, postgres, run queue) with the sobol
location — a second Helm release would spend ~3 extra control-plane pods
of the NRP pod budget for nothing.

This module must NOT import ``nrp.dagster_pipeline`` (it pulls in pymc /
SALib at module scope and would re-couple the locations).
"""

import dagster as dg

from nrp.saturn_assets import (
    saturn_backward_footprint,
    saturn_forward_verification,
    saturn_inferred_emissions,
    saturn_nestor_job,
)
from nrp.shared_defs import (
    make_executor,
    make_resources,
    nrp_run_failure_to_slack,
    nrp_run_start_to_slack,
)

defs = dg.Definitions(
    jobs=[saturn_nestor_job],
    assets=[
        saturn_backward_footprint,
        saturn_inferred_emissions,
        saturn_forward_verification,
    ],
    sensors=[
        nrp_run_failure_to_slack,
        nrp_run_start_to_slack,
    ],
    resources=make_resources(),
    # The three assets form a dependency chain, so steps are serial anyway;
    # max_concurrent=1 caps this workload at run pod + one step pod so a
    # HYSPLIT run fits beside an active sobol backfill under the NRP
    # 4-pod policy.
    executor=make_executor(max_concurrent=1),
)
