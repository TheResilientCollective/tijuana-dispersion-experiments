"""Dagster pipeline for NRP-side calibration workloads.

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

from nrp import mcmc

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
            },
        },
    },
}

_AGGREGATOR_K8S_TAGS = {
    "dagster-k8s/config": {
        "container_config": {
            "resources": {
                "requests": {"cpu": "1", "memory": "4Gi"},
                "limits": {"cpu": "2", "memory": "8Gi"},
            },
        },
    },
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


class McmcConfig(dg.Config):
    """Run-time config for MCMC calibration.

    Draws posterior samples over the 11 emission parameters using
    Sobol-informed priors. Each chain materialises as an independent
    partition; the aggregator collects all chains and computes diagnostics.
    """

    n_chains: int = 9
    n_draws: int = 5000
    n_tune: int = 2500
    seed: int = 42
    window_start: str = sobol.DEFAULT_WINDOW[0]
    window_end: str = sobol.DEFAULT_WINDOW[1]
    obs_sigma: float = 10.0


@dg.asset(
    partitions_def=sobol_partitions,
    group_name="sobol_sensitivity",
    op_tags=_WORKER_K8S_TAGS,
    io_manager_key="s3_io",
)
def sobol_chunk_results(
    context: AssetExecutionContext,
    config: SobolConfig,
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
        "sobol chunk %s: rows [%d, %d) of %d",
        context.partition_key,
        start,
        end,
        samples.shape[0],
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
        ),
    },
)
def sobol_aggregate(
    context: AssetExecutionContext,
    chunks: dict[str, dict[str, Any]],
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
        f"(S_T={top['ST']:.3f} on {top['metric']})",
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
                indices.sort_values("ST", ascending=False).head(10).to_markdown(index=False),
            ),
        },
    )


@dg.asset(
    group_name="sobol_sensitivity",
    op_tags=_AGGREGATOR_K8S_TAGS,
    io_manager_key="s3_io",
    # required_resource_keys={"s3"},
    ins={"sobol_aggregate": dg.AssetIn("sobol_aggregate")},
)
def sobol_post_analysis(
    context: AssetExecutionContext,
    config: SobolConfig,
    sobol_aggregate: dict[str, Any],
    s3: S3Resource,
) -> dg.MaterializeResult:
    """Post-analysis + archival snapshot for a Sobol run.

    Computes the diagnostics an operator would otherwise have to run
    by hand against the bucket: convergence telemetry, per-metric
    top-N, global parameter ranking, magnitude-vs-shape decomposition,
    interaction table, dropout candidates (flagged as
    *window-specific* — a single run cannot establish global
    inertness, see calibration_status 2026-05-22).

    Persists a per-run archival snapshot to
    ``s3://<bucket>/runs/{tag}/`` (separate from the IO manager's
    asset-keyed "latest" pointer at ``dagster/runs/sobol_aggregate``)
    so multi-window / multi-seed studies do not overwrite each other.
    Returns ``MaterializeResult`` with the headline numbers surfaced
    as Dagster UI metadata.
    """
    import io
    import json as _json

    indices = pd.DataFrame(sobol_aggregate["indices"])

    diag = sobol.convergence_diagnostics(indices)
    glob = sobol.global_ranking(indices)
    topn = sobol.top_n_per_metric(indices, n=5)
    splits = sobol.magnitude_vs_shape_split(indices)
    inter = sobol.interaction_table(indices)
    drops = sobol.dropout_candidates(indices)

    tag = sobol.run_tag(
        config.window_start,
        config.window_end,
        config.n_base_samples,
        config.seed,
    )

    # ----- archival snapshot to s3://<bucket>/runs/{tag}/ -----
    bucket = os.getenv("DAGSTER_S3_BUCKET")
    archived: dict[str, str] = {}
    if bucket:
        # s3 = context.resources.s3.get_client()  # boto3 client
        prefix = f"runs/{tag}"
        # 1) indices, full table
        buf_p = io.BytesIO()
        indices.to_parquet(buf_p, index=False)
        s3.put_object(Bucket=bucket, Key=f"{prefix}/sobol_indices.parquet", Body=buf_p.getvalue())
        archived["indices"] = f"s3://{bucket}/{prefix}/sobol_indices.parquet"
        # 2) diagnostics + summaries, machine-readable
        analysis = {
            "tag": tag,
            "window": [config.window_start, config.window_end],
            "n_base_samples": config.n_base_samples,
            "seed": config.seed,
            "convergence": diag,
            "global_ranking": glob.to_dict(orient="records"),
            "top_n_per_metric": topn.to_dict(orient="records"),
            "magnitude_top": splits["magnitude"].to_dict(orient="records"),
            "shape_top": splits["shape"].to_dict(orient="records"),
            "interaction_table": inter.to_dict(orient="records"),
            "dropout_candidates_window_specific": drops,
        }
        s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}/analysis.json",
            Body=_json.dumps(analysis, indent=2).encode(),
        )
        archived["analysis"] = f"s3://{bucket}/{prefix}/analysis.json"
        # 3) human-readable summary
        md = (
            f"# Sobol run `{tag}`\n\n"
            f"window: **{config.window_start} → {config.window_end}** | "
            f"N={config.n_base_samples} | seed={config.seed}\n\n"
            f"**Converged: {diag['is_converged']}** "
            f"(median ST_conf/|ST| {diag['st_conf_over_st_median']:.3f}, "
            f"p90 {diag['st_conf_over_st_p90']:.3f}, "
            f"negative-S1 rows {diag['rows_with_negative_s1']})\n\n"
            f"## Global ranking (mean ST)\n\n"
            f"{glob.to_markdown(index=False)}\n\n"
            f"## Magnitude fit (rms / peak_ratio)\n\n"
            f"{splits['magnitude'].head(8).to_markdown(index=False)}\n\n"
            f"## Shape fit (corr)\n\n"
            f"{splits['shape'].head(8).to_markdown(index=False)}\n\n"
            f"## Top-5 by ST per metric\n\n"
            f"{topn.to_markdown(index=False)}\n\n"
            f"## Window-specific dropout candidates "
            f"(NOT global — need multi-window confirmation)\n\n"
            f"{drops or '(none)'}\n"
        )
        s3.put_object(Bucket=bucket, Key=f"{prefix}/summary.md", Body=md.encode())
        archived["summary"] = f"s3://{bucket}/{prefix}/summary.md"
    else:
        # No S3 — local dev / smoke. Skip archival; analysis is still
        # in MaterializeResult metadata + the asset's IO-manager value.
        log.info("DAGSTER_S3_BUCKET unset; skipping archival write to runs/%s/", tag)

    # ----- MaterializeResult: surface headline in Dagster UI -----
    return dg.MaterializeResult(
        value={
            "tag": tag,
            "convergence": diag,
            "global_ranking": glob.to_dict(orient="records"),
            "top_n_per_metric": topn.to_dict(orient="records"),
            "dropout_candidates_window_specific": drops,
            "archived": archived,
        },
        metadata={
            "tag": tag,
            "converged": diag["is_converged"],
            "st_conf_over_st_median": diag["st_conf_over_st_median"],
            "rows_with_negative_s1": diag["rows_with_negative_s1"],
            "n_parameters": len(glob),
            "dropout_candidates_window_specific": ", ".join(drops) if drops else "(none)",
            "global_ranking_preview": dg.MetadataValue.md(glob.head(11).to_markdown(index=False)),
            "archived_snapshot": dg.MetadataValue.md(
                "\n".join(f"- `{k}`: `{v}`" for k, v in archived.items()) or "(no S3 archive)",
            ),
        },
    )


# ============================================================
# MCMC workload
# ============================================================


@dg.asset(
    group_name="mcmc_posterior",
    op_tags=_WORKER_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
    ins={"sobol_aggregate": dg.AssetIn("sobol_aggregate")},
)
def mcmc_chain_results(
    context: AssetExecutionContext,
    config: McmcConfig,
    sobol_aggregate: dict[str, Any],
) -> dict[str, Any]:
    """Run MCMC posterior sampling using Sobol-informed priors.

    Samples 9 chains × 5000 draws over 11 emission parameters.
    Uses Sobol ST indices to set prior widths: high-ST → tight,
    low-ST → wide. Likelihood is a normal fit to the 9 metrics
    (3 receptors × 3 fit types).

    Returns ArviZ InferenceData as a pickled dict.
    """
    import arviz as az

    context.log.info(
        f"MCMC sampling: {config.n_chains} chains × {config.n_draws - config.n_tune} "
        f"posterior draws (+ {config.n_tune} tune)"
    )

    # Build priors from Sobol baseline
    priors = mcmc.build_priors()
    context.log.info(f"Priors: {len(priors)} parameters")
    for p, spec in priors.items():
        context.log.info(f"  {p}: {spec.dist_type}")

    # TODO: Load observation data for the window
    # For now, placeholder: forward_model_fn needs to be wired to the actual model
    # obs = load_obs_for_window(config.window_start, config.window_end)
    obs = {
        "rms__SAN YSIDRO": np.random.randn(100),
        "rms__NESTOR - BES": np.random.randn(100),
        "rms__IB CIVIC CTR": np.random.randn(100),
        "peak_ratio__SAN YSIDRO": np.random.randn(100),
        "peak_ratio__NESTOR - BES": np.random.randn(100),
        "peak_ratio__IB CIVIC CTR": np.random.randn(100),
        "corr__SAN YSIDRO": np.random.randn(100),
        "corr__NESTOR - BES": np.random.randn(100),
        "corr__IB CIVIC CTR": np.random.randn(100),
    }

    # TODO: Wire forward_model_fn to the actual dispersion model
    def forward_model_fn(params):
        return {k: np.random.randn(100) for k in obs}

    model = mcmc.build_model(obs, forward_model_fn, priors, obs_sigma=config.obs_sigma)
    idata = mcmc.sample_posterior(
        model,
        n_chains=config.n_chains,
        n_draws=config.n_draws,
        n_tune=config.n_tune,
        seed=config.seed,
    )

    context.log.info("MCMC sampling complete; computing diagnostics...")
    diag = mcmc.diagnostics(idata)

    return {
        "idata": az.to_dict(idata),
        "diagnostics": diag,
        "config": {
            "n_chains": config.n_chains,
            "n_draws_posterior": config.n_draws - config.n_tune,
            "n_tune": config.n_tune,
            "seed": config.seed,
            "window": [config.window_start, config.window_end],
        },
    }


@dg.asset(
    deps=[mcmc_chain_results],
    group_name="mcmc_posterior",
    op_tags=_AGGREGATOR_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3", "slack"},
)
def mcmc_aggregate(
    context: AssetExecutionContext,
    config: McmcConfig,
    mcmc_chain_results: dict[str, Any],
) -> dg.MaterializeResult:
    """Aggregate MCMC results and surface diagnostics.

    Computes Rhat, effective sample size, and posterior predictive
    performance on a held-out window (if available).
    """

    diag = mcmc_chain_results.get("diagnostics", {})
    config_dict = mcmc_chain_results.get("config", {})

    context.log.info(f"MCMC aggregate: {len(diag)} parameters")
    converged = diag.get("_summary", {}).get("all_converged", False)
    max_rhat = diag.get("_summary", {}).get("max_rhat", float("inf"))

    context.log.info(f"Convergence: {'✓' if converged else '✗'} (max Rhat: {max_rhat:.4f})")

    return dg.MaterializeResult(
        value=mcmc_chain_results,
        metadata={
            "n_chains": config_dict.get("n_chains"),
            "n_posterior_draws": config_dict.get("n_draws_posterior"),
            "converged": converged,
            "max_rhat": float(max_rhat),
            "diagnostics_summary": dg.MetadataValue.md(
                f"**Convergence**: {'PASS' if converged else 'FAIL'}\n\n"
                f"**Max Rhat**: {max_rhat:.4f} (threshold: 1.01)\n\n"
                f"**Parameters**: {len([d for d in diag if d != '_summary'])}"
            ),
        },
    )


# ============================================================
# Cross-validation workload (hold-out window evaluation)
# ============================================================


@dg.asset(
    partitions_def=cv_fold_partitions,
    group_name="loo_cv",
    op_tags=_WORKER_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
    ins={"mcmc_chain_results": dg.AssetIn("mcmc_chain_results")},
)
def cv_fold_results(
    context: AssetExecutionContext,
    mcmc_chain_results: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate posterior predictive on a held-out window.

    Each partition corresponds to one event/window to hold out.
    Uses the posterior samples from mcmc_chain_results to compute
    predictions on the held-out data.

    TODO: This is scaffolding. Real implementation should:
      - Fit MCMC on all windows EXCEPT this one
      - Evaluate posterior predictive on the held-out window
      - Return RMSE per metric + overall mean RMSE
    """

    held_out_event = context.partition_key
    context.log.info(f"Hold-out CV fold: {held_out_event}")

    # TODO: Load observations for held-out event
    obs_holdout = {
        "rms__SAN YSIDRO": np.random.randn(100),
        "rms__NESTOR - BES": np.random.randn(100),
        "rms__IB CIVIC CTR": np.random.randn(100),
        "peak_ratio__SAN YSIDRO": np.random.randn(100),
        "peak_ratio__NESTOR - BES": np.random.randn(100),
        "peak_ratio__IB CIVIC CTR": np.random.randn(100),
        "corr__SAN YSIDRO": np.random.randn(100),
        "corr__NESTOR - BES": np.random.randn(100),
        "corr__IB CIVIC CTR": np.random.randn(100),
    }

    # TODO: Wire forward_model_fn to actual dispersion model
    def forward_model_fn(params):
        return {k: np.random.randn(100) for k in obs_holdout}

    # TODO: Restore InferenceData from mcmc_chain_results
    # idata = az.from_dict(mcmc_chain_results.get("idata", {}))
    # Compute posterior predictive on held-out window
    cv_metrics = mcmc.posterior_predictive_cv(
        None,  # idata placeholder — requires wiring
        forward_model_fn,
        obs_holdout,
    )

    return {
        "held_out_event": held_out_event,
        "cv_metrics": cv_metrics,
    }


@dg.asset(
    deps=[cv_fold_results],
    group_name="loo_cv",
    op_tags=_AGGREGATOR_K8S_TAGS,
    io_manager_key="s3_io",
    required_resource_keys={"s3", "slack"},
)
def cv_aggregate(
    context: AssetExecutionContext, cv_fold_results: dict[str, Any]
) -> dg.MaterializeResult:
    """Aggregate cross-validation results across all hold-out folds.

    Computes mean RMSE and coverage metrics across folds.
    """
    context.log.info("CV aggregate: collecting hold-out fold results...")

    # TODO: Aggregate cv_fold_results from all partitions
    # For now, placeholder
    all_cv_metrics = {}
    mean_rmse = 0.0

    return dg.MaterializeResult(
        value={"cv_metrics_aggregate": all_cv_metrics},
        metadata={
            "n_folds": 0,  # TODO
            "mean_rmse": float(mean_rmse),
            "cv_summary": dg.MetadataValue.md(
                f"**Cross-validation RMSE**: {mean_rmse:.2f} ppb\n\n**Folds evaluated**: 0"  # TODO
            ),
        },
    )


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


# ============================================================
# Definitions
# ============================================================

# Resources. If/when tj_h2s_prediction becomes pip-installable, replace
# these with imports from tj_h2s_prediction.resources and remove resources.py.
# Asset code stays the same — it only references resource keys.

# Explicit job for "materialise sobol_aggregate + sobol_post_analysis"
# so submit_sobol.py can launch them by a stable jobName via the
# Dagster GraphQL API (rather than depending on the implicit
# `__ASSET_JOB`). Discoverable in `dg list defs` and the UI.
sobol_aggregate_job = dg.define_asset_job(
    name="sobol_aggregate_job",
    selection=dg.AssetSelection.assets("sobol_aggregate", "sobol_post_analysis"),
)


defs = dg.Definitions(
    jobs=[sobol_aggregate_job],
    assets=[
        sobol_chunk_results,
        sobol_aggregate,
        sobol_post_analysis,
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
                ),
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
                "/var/run/secrets/kubernetes.io/serviceaccount/token",
            ),
        },
    )
    if os.getenv("KUBERNETES_SERVICE_HOST")
    else dg.multiprocess_executor,
)
