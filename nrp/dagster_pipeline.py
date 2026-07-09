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

import json as _json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dagster as dg
import numpy as np
import pandas as pd
from dagster import AssetExecutionContext, RunFailureSensorContext, RunStatusSensorContext
from dagster_aws.s3 import S3PickleIOManager, S3Resource
from dagster_k8s import k8s_job_executor

from nrp import mcmc
from nrp.runstore import RunManifest, write_manifest

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

# Leave-one-event-out CV registry. Each event maps to the calibration
# `window` it lives in and the `holdout` sub-range to exclude when fitting
# and then predict. Add events (with their windows) as documented; folds
# whose window data isn't in the baked parquet skip gracefully.
CV_EVENTS: dict[str, dict[str, tuple[str, str]]] = {
    "2026_03_14_stewarts_drain": {
        "window": ("2026-03-13", "2026-03-16"),
        "holdout": ("2026-03-14", "2026-03-15"),
    },
    "2026_02_10_stewarts_drain": {
        "window": ("2026-02-08", "2026-02-11"),
        "holdout": ("2026-02-10", "2026-02-11"),
    },
    "2024_12_02_smugglers_gulch": {
        "window": ("2024-12-01", "2024-12-04"),
        "holdout": ("2024-12-02", "2024-12-03"),
    },
}
KNOWN_EVENTS = list(CV_EVENTS)
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

# MCMC runs ONE SMC chain per partition/pod (see mcmc_chain_results), so
# each pod is single-process (cores=1) and gets the full memory to itself —
# no cross-chain contention. This is what fixed the 8Gi OOM that hit when
# 4 chains shared one pod. 8Gi is generous headroom for a single chain.
_MCMC_K8S_TAGS = {
    "dagster-k8s/config": {
        "container_config": {
            "resources": {
                "requests": {"cpu": "1", "memory": "2Gi"},
                "limits": {"cpu": "2", "memory": "8Gi"},
            },
        },
    },
}

# NRP worker nodes are preemptible — long step pods (multi-hour SMC chains,
# CV folds) get reaped mid-run. A step-level retry makes the step relaunch
# on a fresh pod instead of failing the partition, so backfills self-heal
# instead of needing manual re-submission. delay lets the scheduler settle.
_PREEMPT_RETRY = dg.RetryPolicy(max_retries=5, delay=60)


def _archive_prefix(kind: str, tag: str) -> str:
    """S3 key prefix for a durable per-run archive: ``<root>/<kind>/<tag>``.

    The root defaults to ``runs`` and is overridable via the
    ``S3_ARCHIVE_PREFIX`` env var, so where results are published is a
    deployment parameter rather than hardcoded. Bucket + endpoint are
    already env (``DAGSTER_S3_BUCKET`` / ``S3_ENDPOINT_URL``).
    """
    root = os.getenv("S3_ARCHIVE_PREFIX", "runs").strip("/")
    return f"{root}/{kind}/{tag}"


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

    # SMC config. n_draws is the number of SMC *particles* per chain (not
    # NUTS draws); n_tune is unused under SMC (no separate tuning phase)
    # and kept only so older call sites don't break. Each particle costs a
    # full dispersion forward run over the window, so scale deliberately.
    n_chains: int = 4
    n_draws: int = 2000
    n_tune: int = 0
    seed: int = 42
    window_start: str = sobol.DEFAULT_WINDOW[0]
    window_end: str = sobol.DEFAULT_WINDOW[1]
    obs_sigma: float = 10.0


@dg.asset(
    partitions_def=sobol_partitions,
    group_name="sobol_sensitivity",
    op_tags=_WORKER_K8S_TAGS,
    retry_policy=_PREEMPT_RETRY,
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

    # Carry the run config in the chunk's own value. Downstream assets
    # (sobol_aggregate → sobol_post_analysis) read it from the data instead
    # of run config, so declarative-automation runs — which get no run
    # config — still tag the archive with the correct window/N/seed.
    cfg_meta = {
        "window_start": config.window_start,
        "window_end": config.window_end,
        "n_base_samples": config.n_base_samples,
        "seed": config.seed,
    }
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
            value={
                "start": start,
                "end": end,
                "param_names": [],
                "metric_columns": [],
                "rows": [],
                "config": cfg_meta,
            },
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
            "config": cfg_meta,
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
    pool="nrp_heavy",  # non-exempt (2 CPU/8Gi) — bound by the NRP 4-pod limit
    retry_policy=_PREEMPT_RETRY,
    io_manager_key="s3_io",
    required_resource_keys={"slack"},
    # Self-driving: materialise once all 100 chunk partitions are present
    # and at least one is newly updated (eager holds until no dep is
    # missing). Kicking off the chunk backfill is the only manual step;
    # aggregation then fires automatically — no more manual `dg launch`.
    automation_condition=dg.AutomationCondition.eager(),
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
    # Config travels with the data (every chunk carries an identical copy),
    # so post-analysis can tag the archive correctly under automation.
    run_cfg = next(iter(chunks.values()), {}).get("config")
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
        value={"indices": indices.to_dict(orient="records"), "config": run_cfg},
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
    pool="nrp_heavy",  # non-exempt (2 CPU/8Gi) — bound by the NRP 4-pod limit
    retry_policy=_PREEMPT_RETRY,
    io_manager_key="s3_io",
    # required_resource_keys={"s3"},
    # Self-driving: fire as soon as sobol_aggregate is (re)materialised.
    automation_condition=dg.AutomationCondition.eager(),
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
    top = indices.sort_values("ST", ascending=False).head(1).iloc[0]

    diag = sobol.convergence_diagnostics(indices)
    glob = sobol.global_ranking(indices)
    topn = sobol.top_n_per_metric(indices, n=5)
    splits = sobol.magnitude_vs_shape_split(indices)
    inter = sobol.interaction_table(indices)
    drops = sobol.dropout_candidates(indices)

    # Prefer config carried with the data (correct under automation, where
    # there is no run config); fall back to run config for manual launches.
    carried = sobol_aggregate.get("config") or {}
    window_start = carried.get("window_start", config.window_start)
    window_end = carried.get("window_end", config.window_end)
    n_base_samples = carried.get("n_base_samples", config.n_base_samples)
    seed = carried.get("seed", config.seed)

    tag = sobol.run_tag(window_start, window_end, n_base_samples, seed)

    # ----- archival snapshot to s3://<bucket>/runs/sobol/{tag}/ -----
    bucket = os.getenv("DAGSTER_S3_BUCKET")
    git_sha = os.getenv("DAGSTER_GIT_SHA", "unknown")
    image_digest = os.getenv("DAGSTER_IMAGE_DIGEST", "unknown")
    archived: dict[str, str] = {}
    if bucket:
        s3_client = s3.get_client()  # boto3 client
        prefix = _archive_prefix("sobol", tag)
        # 1) indices, full table
        buf_p = io.BytesIO()
        indices.to_parquet(buf_p, index=False)
        s3_client.put_object(
            Bucket=bucket, Key=f"{prefix}/sobol_indices.parquet", Body=buf_p.getvalue()
        )
        archived["indices"] = f"{prefix}/sobol_indices.parquet"
        # 2) diagnostics + summaries, machine-readable
        analysis = {
            "tag": tag,
            "window": [window_start, window_end],
            "n_base_samples": n_base_samples,
            "seed": seed,
            "convergence": diag,
            "global_ranking": glob.to_dict(orient="records"),
            "top_n_per_metric": topn.to_dict(orient="records"),
            "magnitude_top": splits["magnitude"].to_dict(orient="records"),
            "shape_top": splits["shape"].to_dict(orient="records"),
            "interaction_table": inter.to_dict(orient="records"),
            "dropout_candidates_window_specific": drops,
        }
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/analysis.json",
            Body=_json.dumps(analysis, indent=2).encode(),
        )
        archived["analysis"] = f"{prefix}/analysis.json"
        # 3) human-readable summary
        md = (
            f"# Sobol run `{tag}`\n\n"
            f"window: **{window_start} → {window_end}** | "
            f"N={n_base_samples} | seed={seed}\n\n"
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
        s3_client.put_object(Bucket=bucket, Key=f"{prefix}/summary.md", Body=md.encode())
        archived["summary"] = f"{prefix}/summary.md"
        # 4) manifest (self-describing metadata + artifact pointers)
        manifest = RunManifest(
            kind="sobol",
            tag=tag,
            window=[window_start, window_end],
            n_base_samples=n_base_samples,
            seed=seed,
            git_sha=git_sha,
            image_digest=image_digest,
            status="complete",
            created=_json.dumps(datetime.now(UTC), default=str),
            headline={"top_param": top["parameter"], "top_ST": float(top["ST"])},
            artifacts=archived,
        )
        write_manifest(s3_client, bucket, manifest)
    else:
        # No S3 — local dev / smoke. Skip archival; analysis is still
        # in MaterializeResult metadata + the asset's IO-manager value.
        log.info("DAGSTER_S3_BUCKET unset; skipping archival write to runs/sobol/%s/", tag)

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
# Ledger and site generation
# ============================================================


@dg.asset(
    group_name="reporting",
    op_tags=_AGGREGATOR_K8S_TAGS,
    pool="nrp_heavy",  # non-exempt (2 CPU/8Gi) — bound by the NRP 4-pod limit
    retry_policy=_PREEMPT_RETRY,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
)
def build_index(
    context: AssetExecutionContext,
) -> dg.MaterializeResult:
    """Build the run ledger (runs.jsonl) and browsable site (index.html).

    Scans all run manifests in S3, aggregates into a sortable ledger, and
    generates a static HTML site. Runs on-demand or after major calibration
    runs complete. Safe to run repeatedly — reads from S3, overwrites site/.
    """
    from nrp.runstore import build_ledger, build_site

    bucket = os.getenv("DAGSTER_S3_BUCKET")
    if not bucket:
        log.warning("DAGSTER_S3_BUCKET unset; skipping index build")
        return dg.MaterializeResult(
            value={},
            metadata={"status": "skipped (no S3 bucket)"},
        )

    s3_client = context.resources.s3.get_client()

    # Aggregate all manifests
    ledger = build_ledger(s3_client, bucket)
    log.info("Indexed %d runs from S3", len(ledger))

    # Generate site
    html = build_site(ledger)
    s3_client.put_object(
        Bucket=bucket,
        Key="site/index.html",
        Body=html.encode(),
        ContentType="text/html",
    )

    # Write ledger as JSONL (one manifest per line)
    ledger_lines = [
        _json.dumps(asdict(m), default=str)
        for m in sorted(ledger.values(), key=lambda m: m.created or "", reverse=True)
    ]
    s3_client.put_object(
        Bucket=bucket,
        Key="ledger/runs.jsonl",
        Body="\n".join(ledger_lines).encode(),
        ContentType="application/x-ndjson",
    )

    return dg.MaterializeResult(
        value={"ledger_size": len(ledger), "site_url": f"s3://{bucket}/site/index.html"},
        metadata={
            "runs_indexed": len(ledger),
            "site_url": f"s3://{bucket}/site/index.html",
            "ledger_url": f"s3://{bucket}/ledger/runs.jsonl",
        },
    )


# ============================================================
# MCMC workload
# ============================================================


@dg.asset(
    partitions_def=mcmc_partitions,
    group_name="mcmc_posterior",
    op_tags=_MCMC_K8S_TAGS,
    pool="nrp_heavy",  # non-exempt (2 CPU/8Gi) — bound by the NRP 4-pod limit
    retry_policy=_PREEMPT_RETRY,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
    ins={"sobol_aggregate": dg.AssetIn("sobol_aggregate")},
)
def mcmc_chain_results(
    context: AssetExecutionContext,
    config: McmcConfig,
    sobol_aggregate: dict[str, Any],
) -> dict[str, Any]:
    """Run ONE SMC chain (this partition) of the MCMC calibration.

    One partition = one independent chain, each in its own K8s pod (the
    README's fan-out design). This isolates each chain's memory — the
    single-pod, all-chains-at-once approach OOMKilled at 8Gi. Chains
    differ only by seed (``config.seed + chain_idx``); mcmc_aggregate
    concatenates them for cross-chain Rhat/ESS.

    Uses Sobol-informed priors and the published tijuana_dispersion
    forward model (via sobol.predict_concentrations) against the observed
    H2S series. Returns a single-chain ArviZ InferenceData as a dict.
    """
    chain_idx = int(context.partition_key.split("_")[1])
    chain_seed = config.seed + chain_idx

    # Real observations + forward model, reusing the exact Sobol machinery
    # so the calibration science is identical to the sensitivity analysis.
    df = sobol.load_window(sobol.DEFAULT_PARQUET, (config.window_start, config.window_end))
    drivers, met, hours = sobol.make_drivers_and_met(df)
    obs_mat = sobol.build_obs(df, hours, sobol.RECEPTOR_NAMES)  # (n_hours, n_receptors)
    valid = ~np.isnan(obs_mat)
    obs_flat = obs_mat[valid]
    if obs_flat.size == 0:
        raise ValueError("No H2S observations in the window — cannot calibrate.")

    param_names = list(sobol.PARAM_RANGES)

    def forward_model_fn(params: dict[str, float]) -> np.ndarray:
        """Concrete param dict → predicted concentrations at the valid obs points."""
        row = np.array([params[n] for n in param_names], dtype=float)
        pred = sobol.predict_concentrations(row, param_names, drivers, met)
        return pred[valid]

    # Sobol-informed priors from THIS study's ST indices (not a hardcoded table).
    sobol_indices = pd.DataFrame(sobol_aggregate["indices"])
    priors = mcmc.build_priors(sobol_indices=sobol_indices)
    context.log.info(
        "MCMC chain %s (seed %d): %d obs points, %d params; single-chain SMC "
        "× %d particles (window %s→%s)",
        context.partition_key,
        chain_seed,
        obs_flat.size,
        len(param_names),
        config.n_draws,
        config.window_start,
        config.window_end,
    )

    model = mcmc.build_model(obs_flat, forward_model_fn, priors, obs_sigma=config.obs_sigma)
    # One chain per pod — chains=1. Cross-chain diagnostics happen in the aggregate.
    idata = mcmc.sample_posterior(
        model,
        n_chains=1,
        n_draws=config.n_draws,
        seed=chain_seed,
    )
    context.log.info("MCMC chain %s complete", context.partition_key)

    return {
        "idata": idata.to_dict(),
        "config": {
            "chain": context.partition_key,
            "chain_idx": chain_idx,
            "n_particles": config.n_draws,
            "seed": chain_seed,
            "base_seed": config.seed,
            "window": [config.window_start, config.window_end],
            "obs_sigma": config.obs_sigma,
            "n_obs": int(obs_flat.size),
        },
    }


@dg.asset(
    group_name="mcmc_posterior",
    op_tags=_AGGREGATOR_K8S_TAGS,
    pool="nrp_heavy",  # non-exempt (2 CPU/8Gi) — bound by the NRP 4-pod limit
    retry_policy=_PREEMPT_RETRY,
    io_manager_key="s3_io",
    required_resource_keys={"s3", "slack"},
    ins={
        "chains": dg.AssetIn(
            "mcmc_chain_results",
            partition_mapping=dg.AllPartitionMapping(),
        ),
    },
)
def mcmc_aggregate(
    context: AssetExecutionContext,
    chains: dict[str, dict[str, Any]],
) -> dg.MaterializeResult:
    """Combine the per-chain posteriors and compute cross-chain diagnostics.

    ``chains`` is ``{chain_NN: chain_value}`` for every partition. Each
    chain ran single-chain SMC in its own pod; here we concatenate them
    along the chain dimension so Rhat/ESS (which need ≥2 chains) are
    meaningful. The combined posterior is the calibration result.
    """
    import io

    import arviz as az

    slack: SlackWebhookResource = context.resources.slack

    ordered = sorted(chains.items())  # deterministic chain order
    idatas = [az.from_dict(posterior=v["idata"]["posterior"]) for _, v in ordered]
    combined = az.concat(idatas, dim="chain")
    cfg = ordered[0][1].get("config", {})  # identical across chains except seed
    n_chains = len(ordered)

    diag = mcmc.diagnostics(combined)
    summary = diag["_summary"]
    converged = summary["all_converged"]
    max_rhat = summary["max_rhat"]

    # ----- posterior summary + bound-railing -----
    summ_df = (
        az.summary(combined, hdi_prob=0.94).reset_index().rename(columns={"index": "parameter"})
    )
    railing = mcmc.bound_railing(summ_df, sobol.PARAM_RANGES)

    # ----- posterior-predictive skill (best-effort; needs the forward model) -----
    window = cfg.get("window", list(sobol.DEFAULT_WINDOW))
    predictive: list[dict[str, Any]] = []
    try:
        df = sobol.load_window(sobol.DEFAULT_PARQUET, (window[0], window[1]))
        drivers, met, _hours = sobol.make_drivers_and_met(df)
        obs_mat = sobol.build_obs(df, _hours, sobol.RECEPTOR_NAMES)
        param_names = list(sobol.PARAM_RANGES)
        draws = mcmc.posterior_param_draws(combined, param_names, n_samples=100)
        predictive = mcmc.predictive_skill(
            draws,
            lambda row: sobol.predict_concentrations(row, param_names, drivers, met),
            obs_mat,
            sobol.RECEPTOR_NAMES,
        )
    except Exception as exc:  # predictive is a bonus — never fail the report over it
        context.log.warning("posterior-predictive skipped: %s", exc)

    context.log.info(
        "MCMC aggregate: %d chains, max Rhat %.4f, converged=%s, %d railing param(s)",
        n_chains,
        max_rhat,
        converged,
        len(railing),
    )

    # ----- durable archive at runs/mcmc/<tag>/ -----
    base_seed = cfg.get("base_seed", cfg.get("seed"))
    n_particles = cfg.get("n_particles")
    run_date = datetime.now(UTC).strftime("%Y-%m-%d")
    tag = f"{window[0]}_{window[1]}_{n_chains}chains_{n_particles}p_seed{base_seed}_{run_date}"
    bucket = os.getenv("DAGSTER_S3_BUCKET")
    archived: dict[str, str] = {}
    if bucket:
        s3c = context.resources.s3.get_client()
        prefix = _archive_prefix("mcmc", tag)

        samples = combined.posterior.to_dataframe().reset_index()
        buf = io.BytesIO()
        samples.to_parquet(buf, index=False)
        s3c.put_object(
            Bucket=bucket, Key=f"{prefix}/posterior_samples.parquet", Body=buf.getvalue()
        )
        archived["posterior_samples"] = f"{prefix}/posterior_samples.parquet"

        s3c.put_object(
            Bucket=bucket,
            Key=f"{prefix}/posterior_summary.csv",
            Body=summ_df.to_csv(index=False).encode(),
        )
        archived["posterior_summary"] = f"{prefix}/posterior_summary.csv"

        analysis = {
            "tag": tag,
            "window": window,
            "n_chains": n_chains,
            "n_particles": n_particles,
            "base_seed": base_seed,
            "converged": converged,
            "max_rhat": max_rhat,
            "diagnostics": {k: v for k, v in diag.items() if k != "_summary"},
            "bound_railing": railing,
            "posterior_predictive": predictive,
        }
        s3c.put_object(
            Bucket=bucket,
            Key=f"{prefix}/diagnostics.json",
            Body=_json.dumps(analysis, indent=2, default=str).encode(),
        )
        archived["diagnostics"] = f"{prefix}/diagnostics.json"

        rail_md = (
            "\n".join(f"- `{r['parameter']}` at {r['edge']} bound {r['range']}" for r in railing)
            or "(none — all parameters interior)"
        )
        pred_md = (
            pd.DataFrame(predictive).to_markdown(index=False)
            if predictive
            else "(posterior-predictive not computed)"
        )
        md = (
            f"# MCMC calibration `{tag}`\n\n"
            f"window **{window[0]} → {window[1]}** | {n_chains} chains × "
            f"{n_particles} particles | base seed {base_seed}\n\n"
            f"**Converged: {converged}** (max Rhat {max_rhat:.4f}, threshold 1.01)\n\n"
            f"## Posterior (94% HDI)\n\n{summ_df.to_markdown(index=False)}\n\n"
            f"## Parameters railing against bounds (widen these)\n\n{rail_md}\n\n"
            f"## Posterior-predictive skill per receptor\n\n{pred_md}\n"
        )
        s3c.put_object(Bucket=bucket, Key=f"{prefix}/summary.md", Body=md.encode())
        archived["summary"] = f"{prefix}/summary.md"

        manifest = RunManifest(
            kind="mcmc",
            tag=tag,
            window=list(window),
            seed=base_seed,
            git_sha=os.getenv("DAGSTER_GIT_SHA", "unknown"),
            image_digest=os.getenv("DAGSTER_IMAGE_DIGEST", "unknown"),
            status="complete",
            created=_json.dumps(datetime.now(UTC), default=str),
            headline={
                "converged": converged,
                "max_rhat": float(max_rhat),
                "n_railing": len(railing),
                "mean_coverage_94": (
                    float(np.mean([p["coverage_94"] for p in predictive])) if predictive else None
                ),
            },
            artifacts=archived,
        )
        write_manifest(s3c, bucket, manifest)
    else:
        context.log.info("DAGSTER_S3_BUCKET unset; skipping archive to runs/mcmc/%s/", tag)

    slack.watch(
        f":game_die: MCMC calibration complete (run {context.run_id[:8]})\n"
        f"Chains: {n_chains} × {n_particles} particles | window {window}\n"
        f"Converged: {converged} (max Rhat {max_rhat:.3f}) | railing: {len(railing)}",
    )

    return dg.MaterializeResult(
        value={
            "idata": combined.to_dict(),
            "diagnostics": diag,
            "config": {**cfg, "n_chains": n_chains},
        },
        metadata={
            "tag": tag,
            "n_chains": n_chains,
            "n_particles": n_particles,
            "converged": converged,
            "max_rhat": float(max_rhat),
            "window": str(window),
            "railing_params": ", ".join(r["parameter"] for r in railing) or "(none)",
            "posterior_summary": dg.MetadataValue.md(summ_df.to_markdown(index=False)),
            "predictive_skill": dg.MetadataValue.md(
                pd.DataFrame(predictive).to_markdown(index=False)
                if predictive
                else "(not computed)"
            ),
            "archived": dg.MetadataValue.md(
                "\n".join(f"- `{k}`: `{v}`" for k, v in archived.items()) or "(no S3 archive)"
            ),
        },
    )


# ============================================================
# Cross-validation workload (hold-out window evaluation)
# ============================================================


@dg.asset(
    partitions_def=cv_fold_partitions,
    group_name="loo_cv",
    op_tags=_MCMC_K8S_TAGS,
    pool="nrp_heavy",  # non-exempt (2 CPU/8Gi) — bound by the NRP 4-pod limit
    retry_policy=_PREEMPT_RETRY,
    io_manager_key="s3_io",
    required_resource_keys={"s3"},
)
def cv_fold_results(
    context: AssetExecutionContext,
    config: McmcConfig,
) -> dict[str, Any]:
    """Leave-one-event-out CV for this partition's event.

    Refits the emission parameters on the event's window with the event's
    hours *excluded*, then predicts those held-out hours — the honest
    out-of-sample test. Returns train (in-sample) and test (held-out)
    posterior-predictive skill per receptor; ``cv_aggregate`` combines
    them into the generalization report. Each fold is its own SMC fit
    (one chain, isolated pod), reusing the exact calibration machinery.
    """
    event = context.partition_key
    ev = CV_EVENTS[event]
    (ws, we), (hs, he) = ev["window"], ev["holdout"]
    context.log.info("CV fold %s: window %s→%s, hold out %s→%s", event, ws, we, hs, he)

    try:
        df = sobol.load_window(sobol.DEFAULT_PARQUET, (ws, we))
    except Exception as exc:  # missing window data → skip, don't fail the whole sweep
        context.log.warning("fold %s skipped: %s", event, exc)
        return {"event": event, "status": f"skipped: {exc}"}

    drivers, met, hours = sobol.make_drivers_and_met(df)
    obs_mat = sobol.build_obs(df, hours, sobol.RECEPTOR_NAMES)  # (n_hours, n_receptors)
    holdout = (hours >= pd.Timestamp(hs)) & (hours < pd.Timestamp(he))
    if holdout.sum() == 0 or (~holdout).sum() == 0:
        return {"event": event, "status": "skipped: empty holdout/train split"}

    param_names = list(sobol.PARAM_RANGES)

    def fwd(row: np.ndarray) -> np.ndarray:
        return sobol.predict_concentrations(row, param_names, drivers, met)

    # --- fit on TRAIN (holdout hours masked out of the likelihood) ---
    train_obs = obs_mat.copy()
    train_obs[holdout, :] = np.nan
    valid_train = ~np.isnan(train_obs)
    if valid_train.sum() == 0:
        return {"event": event, "status": "skipped: no training observations"}

    def forward_train(params: dict[str, float]) -> np.ndarray:
        row = np.array([params[p] for p in param_names], dtype=float)
        return fwd(row)[valid_train]

    priors = mcmc.build_priors(sobol_indices=None)
    model = mcmc.build_model(
        train_obs[valid_train], forward_train, priors, obs_sigma=config.obs_sigma
    )
    idata = mcmc.sample_posterior(model, n_chains=1, n_draws=config.n_draws, seed=config.seed)

    # --- predict: held-out (test) vs in-sample (train) ---
    draws = mcmc.posterior_param_draws(idata, param_names, n_samples=100)
    test_obs = np.where(holdout[:, None], obs_mat, np.nan)
    train_only = np.where(holdout[:, None], np.nan, obs_mat)
    test_skill = mcmc.predictive_skill(draws, fwd, test_obs, sobol.RECEPTOR_NAMES)
    train_skill = mcmc.predictive_skill(draws, fwd, train_only, sobol.RECEPTOR_NAMES)
    context.log.info("CV fold %s complete: %d receptors scored held-out", event, len(test_skill))

    return {
        "event": event,
        "status": "complete",
        "window": [ws, we],
        "holdout": [hs, he],
        "n_particles": config.n_draws,
        "seed": config.seed,
        "train_skill": train_skill,
        "test_skill": test_skill,
    }


@dg.asset(
    group_name="loo_cv",
    op_tags=_AGGREGATOR_K8S_TAGS,
    pool="nrp_heavy",  # non-exempt (2 CPU/8Gi) — bound by the NRP 4-pod limit
    retry_policy=_PREEMPT_RETRY,
    io_manager_key="s3_io",
    required_resource_keys={"s3", "slack"},
    ins={
        "folds": dg.AssetIn(
            "cv_fold_results",
            partition_mapping=dg.AllPartitionMapping(),
        ),
    },
)
def cv_aggregate(
    context: AssetExecutionContext,
    folds: dict[str, dict[str, Any]],
) -> dg.MaterializeResult:
    """Combine LOO-CV folds → out-of-sample skill + generalization report.

    Reports the honest test (held-out) predictive skill averaged over
    folds, alongside the train (in-sample) skill so the generalization
    gap is explicit. Writes a durable runs/cv/<tag>/ report + manifest.
    """
    slack: SlackWebhookResource = context.resources.slack

    def _mean(skill_lists: list[list[dict[str, Any]]], key: str) -> float | None:
        vals = [s[key] for lst in skill_lists for s in lst]
        return float(np.mean(vals)) if vals else None

    complete = {k: v for k, v in folds.items() if v.get("status") == "complete"}
    skipped = {k: v.get("status") for k, v in folds.items() if v.get("status") != "complete"}
    rows: list[dict[str, Any]] = []
    for event, v in sorted(complete.items()):
        for s in v["test_skill"]:
            rows.append({"event": event, "split": "test", **s})
        for s in v["train_skill"]:
            rows.append({"event": event, "split": "train", **s})
    folds_df = pd.DataFrame(rows)

    test_lists = [v["test_skill"] for v in complete.values()]
    train_lists = [v["train_skill"] for v in complete.values()]
    test_rmse, test_corr = _mean(test_lists, "rmse"), _mean(test_lists, "corr")
    train_rmse, train_corr = _mean(train_lists, "rmse"), _mean(train_lists, "corr")
    test_cover = _mean(test_lists, "coverage_94")
    gen_gap = (
        (train_corr - test_corr) if (train_corr is not None and test_corr is not None) else None
    )
    context.log.info(
        "CV aggregate: %d complete, %d skipped | test RMSE=%s corr=%s | gen-gap=%s",
        len(complete),
        len(skipped),
        test_rmse,
        test_corr,
        gen_gap,
    )

    run_date = datetime.now(UTC).strftime("%Y-%m-%d")
    tag = f"loo_cv_{len(complete)}folds_{run_date}"
    bucket = os.getenv("DAGSTER_S3_BUCKET")
    archived: dict[str, str] = {}
    if bucket and not folds_df.empty:
        s3c = context.resources.s3.get_client()
        prefix = _archive_prefix("cv", tag)
        s3c.put_object(
            Bucket=bucket, Key=f"{prefix}/cv_folds.csv", Body=folds_df.to_csv(index=False).encode()
        )
        archived["cv_folds"] = f"{prefix}/cv_folds.csv"
        md = (
            f"# Leave-one-event-out CV `{tag}`\n\n"
            f"folds complete: **{len(complete)}** | skipped: {len(skipped)}\n\n"
            f"## Out-of-sample (held-out) skill\n\n"
            f"- mean RMSE: **{test_rmse:.3f}** ppb\n"
            f"- mean corr: **{test_corr:.3f}**\n"
            f"- mean 94% coverage: **{test_cover:.3f}**\n\n"
            f"## Generalization gap (train − test corr): "
            f"**{gen_gap:.3f}**\n\n"
            f"train mean RMSE {train_rmse:.3f} / corr {train_corr:.3f}\n\n"
            f"## Per-fold, per-receptor\n\n{folds_df.to_markdown(index=False)}\n\n"
            f"## Skipped folds\n\n"
            + ("\n".join(f"- `{k}`: {s}" for k, s in skipped.items()) or "(none)")
        )
        s3c.put_object(Bucket=bucket, Key=f"{prefix}/summary.md", Body=md.encode())
        archived["summary"] = f"{prefix}/summary.md"
        manifest = RunManifest(
            kind="cv",
            tag=tag,
            window=["", ""],
            git_sha=os.getenv("DAGSTER_GIT_SHA", "unknown"),
            image_digest=os.getenv("DAGSTER_IMAGE_DIGEST", "unknown"),
            status="complete",
            created=_json.dumps(datetime.now(UTC), default=str),
            skill={"validation": train_corr, "test": test_corr},
            headline={"n_folds": len(complete), "test_rmse": test_rmse, "gen_gap": gen_gap},
            artifacts=archived,
        )
        write_manifest(s3c, bucket, manifest)

    if test_corr is not None:
        slack.watch(
            f":test_tube: LOO-CV complete ({len(complete)} folds)\n"
            f"Out-of-sample corr {test_corr:.3f}, RMSE {test_rmse:.3f} ppb | "
            f"gen-gap {gen_gap:.3f}",
        )

    return dg.MaterializeResult(
        value={"folds": rows, "skipped": skipped},
        metadata={
            "n_folds_complete": len(complete),
            "n_folds_skipped": len(skipped),
            "test_rmse": test_rmse if test_rmse is not None else float("nan"),
            "test_corr": test_corr if test_corr is not None else float("nan"),
            "test_coverage_94": test_cover if test_cover is not None else float("nan"),
            "generalization_gap": gen_gap if gen_gap is not None else float("nan"),
            "cv_summary": dg.MetadataValue.md(
                folds_df.to_markdown(index=False) if not folds_df.empty else "(no complete folds)"
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

# Evaluates the AutomationConditions on the Sobol aggregate chain so it is
# self-driving: when the 100-partition chunk backfill finishes, sobol_aggregate
# then sobol_post_analysis materialise automatically (no manual dg launch).
# RUNNING by default so it activates on deploy; the daemon runs the evaluation
# tick (same daemon that runs the run queue and backfills).
sobol_automation_sensor = dg.AutomationConditionSensorDefinition(
    name="sobol_automation_sensor",
    target=dg.AssetSelection.assets("sobol_aggregate", "sobol_post_analysis"),
    default_status=dg.DefaultSensorStatus.RUNNING,
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
        sobol_automation_sensor,
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
