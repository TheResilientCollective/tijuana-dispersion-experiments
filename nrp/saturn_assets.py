"""Dagster assets: Saturn Blvd Bridge → NESTOR-BES HYSPLIT back/forward run.

Asset graph (job ``saturn_nestor_job``):

    saturn_backward_footprint → saturn_inferred_emissions → saturn_forward_verification

- **saturn_backward_footprint** — one backward ``hycs_std`` run per NESTOR
  observation hour in the window (unit release at the receptor) → dilution
  sensitivity s(t) at the Saturn Blvd Bridge cell. Needs the HYSPLIT binary
  (worker-hysplit image) + met files (fetched via ``nrp.metfetch``).
- **saturn_inferred_emissions** — pure math: Q(t) = C_obs(t)/s(t) with
  floor/ceiling guards. No HYSPLIT, no met.
- **saturn_forward_verification** — two forward runs from Saturn only
  (constant prior 5 g/s; inferred Q(t) via EMITIMES), sampled at the Nestor
  cell, scored against observations (rms/corr/peak_ratio), archived to
  ``s3://<bucket>/runs/hysplit/{tag}/`` with a runstore manifest so the run
  appears in the ``build_index`` ledger.

Science lives in ``nrp.saturn_nestor`` (CI-testable without the binary);
this module is only the orchestration glue, mirroring the sobol assets'
patterns (config schema, ``s3_io`` IO manager, DAGSTER_S3_BUCKET-gated
archival, MaterializeResult metadata).

NOTE: no ``from __future__ import annotations`` here — PEP 563 string
annotations break Dagster's Pythonic-config type resolution.
"""

import logging
import os
from pathlib import Path
from typing import Any

import dagster as dg
import numpy as np
import pandas as pd
from dagster import AssetExecutionContext
from dagster_aws.s3 import S3Resource

from nrp.runstore import RunManifest, write_manifest

from . import hysplit_exec, metfetch, saturn_nestor

log = logging.getLogger(__name__)

#: HYSPLIT-executing steps: more memory than the sobol workers (met decoding),
#: and enough ephemeral disk to hold met files when met_dir is NOT a mounted
#: PVC (a 3-day HRRR window is ~50 GB — mount a CephFS RWX PVC at
#: $HYSPLIT_METEO_DIR instead of relying on ephemeral storage; see DEPLOYMENT.md).
_HYSPLIT_K8S_TAGS = {
    "dagster-k8s/config": {
        "container_config": {
            "resources": {
                "requests": {"cpu": "1", "memory": "2Gi", "ephemeral-storage": "10Gi"},
                "limits": {"cpu": "2", "memory": "6Gi", "ephemeral-storage": "80Gi"},
            },
        },
    },
}


class SaturnNestorConfig(dg.Config):
    """Run-time config for the Saturn→Nestor back/forward calculation.

    Defaults target the Apr 4 2026 event (peak previously localised to
    ~415 m of Saturn Blvd Bridge). ``met_source`` defaults to HRRR 3 km;
    use ``gdas1`` for a cheap smoke test (~600 MB vs ~50 GB of met).
    """

    window_start: str = saturn_nestor.DEFAULT_WINDOW[0]
    window_end: str = saturn_nestor.DEFAULT_WINDOW[1]
    hours_back: int = 12
    numpar: int = 2500
    met_source: str = "hrrr"
    sensitivity_floor: float = 1e-11
    q_max_g_s: float = 1000.0
    prior_q_g_s: float = saturn_nestor.PRIOR_Q_G_S
    cell_agg: str = "mean3x3"
    parquet_path: str | None = None
    met_dir: str | None = None


def _parquet_path(cfg: SaturnNestorConfig) -> Path:
    return Path(cfg.parquet_path) if cfg.parquet_path else saturn_nestor.DEFAULT_PARQUET


def _tag(cfg: SaturnNestorConfig) -> str:
    return saturn_nestor.run_tag(cfg.window_start, cfg.window_end, cfg.hours_back, cfg.met_source)


@dg.asset(
    group_name="saturn_nestor",
    op_tags=_HYSPLIT_K8S_TAGS,
    io_manager_key="s3_io",
)
def saturn_backward_footprint(
    context: AssetExecutionContext,
    config: SaturnNestorConfig,
) -> dg.MaterializeResult:
    """Backward footprint per observation hour → sensitivity at Saturn.

    Hours with no valid NESTOR H2S are skipped (no run). Each run's CONTROL
    text and raw cdump bytes are kept in the asset value for archival by the
    downstream verification asset.
    """
    obs = saturn_nestor.load_nestor_obs(
        _parquet_path(config), (config.window_start, config.window_end)
    )
    hours_utc = pd.DatetimeIndex(obs["hour_utc"])
    met_files = metfetch.met_files_for(
        config.met_source,
        hours_utc.min() - pd.Timedelta(hours=config.hours_back),
        hours_utc.max(),
    )
    met_dir = metfetch.ensure_met_files(met_files, metfetch.resolve_met_dir(config.met_dir))
    met_names = [m.name for m in met_files]
    setup = saturn_nestor.setup_cfg(numpar=config.numpar)

    records: list[dict[str, Any]] = []
    controls: dict[str, str] = {}
    cdumps: dict[str, bytes] = {}
    n_skipped = 0
    for row in obs.itertuples(index=False):
        hour_utc = pd.Timestamp(row.hour_utc)
        if pd.isna(row.obs_ppb):
            n_skipped += 1
            continue
        run_name = f"backward_{hour_utc.strftime('%Y%m%dT%H')}Z"
        control = saturn_nestor.write_backward_control(
            hour_utc, config.hours_back, str(met_dir), met_names
        )
        result = hysplit_exec.run_control(control, setup)
        grid = saturn_nestor.parse_cdump(result.cdump_path)
        sens, n_nonzero = saturn_nestor.sensitivity_from_backward(grid, agg=config.cell_agg)
        context.log.info(
            "backward %s: obs=%.1f ppb sensitivity=%.3e (g/m3)/(g/hr) nonzero_bins=%d",
            run_name,
            row.obs_ppb,
            sens,
            n_nonzero,
        )
        records.append(
            {
                "hour": pd.Timestamp(row.hour).isoformat(),
                "hour_utc": hour_utc.isoformat(),
                "obs_ppb": float(row.obs_ppb),
                "temp_c": float(row.temp_c) if pd.notna(row.temp_c) else np.nan,
                "wind_speed_ms": (
                    float(row.wind_speed_ms) if pd.notna(row.wind_speed_ms) else np.nan
                ),
                "wind_dir_deg": float(row.wind_dir_deg) if pd.notna(row.wind_dir_deg) else np.nan,
                "sensitivity": sens,
                "n_nonzero_bins": n_nonzero,
            },
        )
        controls[run_name] = control
        cdumps[run_name] = result.cdump_path.read_bytes()

    if not records:
        raise ValueError(
            f"No valid NESTOR observation hours in window "
            f"({config.window_start}, {config.window_end}) — nothing to invert.",
        )
    sens_vals = np.array([r["sensitivity"] for r in records])
    return dg.MaterializeResult(
        value={
            "records": records,
            "controls": controls,
            "cdumps": cdumps,
            "met_files": met_names,
        },
        metadata={
            "n_hours_run": len(records),
            "n_hours_skipped_no_obs": n_skipped,
            "median_sensitivity": float(np.median(sens_vals)),
            "frac_below_floor": float((sens_vals < config.sensitivity_floor).mean()),
            "met_source": config.met_source,
            "met_files": ", ".join(met_names),
        },
    )


@dg.asset(
    group_name="saturn_nestor",
    io_manager_key="s3_io",
)
def saturn_inferred_emissions(
    context: AssetExecutionContext,
    config: SaturnNestorConfig,
    saturn_backward_footprint: dict[str, Any],
) -> dg.MaterializeResult:
    """Back-calculated hourly Saturn emission rate Q(t) — pure math."""
    frame = pd.DataFrame(saturn_backward_footprint["records"])
    inferred = saturn_nestor.infer_emissions(
        frame,
        sensitivity_floor=config.sensitivity_floor,
        q_max_g_s=config.q_max_g_s,
    )
    ok = inferred[inferred["flag"] == "ok"]
    flag_counts = inferred["flag"].value_counts().to_dict()
    context.log.info("inferred emissions: %s", flag_counts)
    return dg.MaterializeResult(
        value={"records": inferred.to_dict(orient="records")},
        metadata={
            "n_hours": len(inferred),
            "flag_counts": dg.MetadataValue.json(flag_counts),
            "median_q_g_s": float(ok["q_g_s"].median()) if not ok.empty else float("nan"),
            "max_q_g_s": float(ok["q_g_s"].max()) if not ok.empty else float("nan"),
            "prior_q_g_s": config.prior_q_g_s,
        },
    )


def _predictions_from_cdump(
    grid: saturn_nestor.CdumpGrid,
    obs_hours_utc: pd.DatetimeIndex,
    temps_c: pd.Series,
    cell_agg: str,
) -> pd.Series:
    """Forward cdump → predicted ppb aligned to observation hours.

    A cdump 1-hour bin is stamped with its sampling STOP time, so the bin for
    obs hour ``h`` (average over [h, h+1), naive UTC) ends at ``h+1``.
    """
    _, lat, lon, _ = saturn_nestor.RECEPTOR
    conc = saturn_nestor.sample_cell(grid, lat, lon, agg=cell_agg)
    by_end = {pd.Timestamp(t): float(v) for t, v in zip(grid.times, conc, strict=True)}
    out = []
    for h in obs_hours_utc:
        end = pd.Timestamp(h) + pd.Timedelta(hours=1)
        gm3 = by_end.get(end)
        if gm3 is None:
            out.append(np.nan)
            continue
        temp = temps_c.get(h, 25.0)
        temp = 25.0 if pd.isna(temp) else float(temp)
        out.append(saturn_nestor.ugm3_to_ppb_h2s(gm3 * 1e6, temp))
    return pd.Series(out, index=obs_hours_utc)


@dg.asset(
    group_name="saturn_nestor",
    op_tags=_HYSPLIT_K8S_TAGS,
    io_manager_key="s3_io",
)
def saturn_forward_verification(
    context: AssetExecutionContext,
    config: SaturnNestorConfig,
    saturn_backward_footprint: dict[str, Any],
    saturn_inferred_emissions: dict[str, Any],
    s3: S3Resource,
) -> dg.MaterializeResult:
    """Forward runs from Saturn (prior + inferred Q) scored at Nestor.

    Both runs start ``hours_back`` before the first observation hour so the
    plume is spun up; pre-window hours carry zero inferred emission (Q(t) is
    only defined on observation hours), which slightly under-feeds the first
    in-window hours of the inferred run — noted in the summary. Archives the
    full run (parquets, metrics, CONTROLs, cdumps, summary.md, manifest) when
    ``DAGSTER_S3_BUCKET`` is set, exactly like ``sobol_post_analysis``.
    """
    import io
    import json as _json
    from datetime import UTC, datetime

    inferred = pd.DataFrame(saturn_inferred_emissions["records"])
    inferred["hour_utc"] = pd.to_datetime(inferred["hour_utc"])
    obs_hours = pd.DatetimeIndex(inferred["hour_utc"])
    obs_ppb = pd.Series(inferred["obs_ppb"].to_numpy(), index=obs_hours)
    temps = pd.Series(inferred["temp_c"].to_numpy(), index=obs_hours)

    start_utc = obs_hours.min() - pd.Timedelta(hours=config.hours_back)
    end_utc = obs_hours.max()
    run_hours = int((end_utc - start_utc) / pd.Timedelta(hours=1)) + 1
    met_files = metfetch.met_files_for(config.met_source, start_utc, end_utc)
    met_dir = metfetch.ensure_met_files(met_files, metfetch.resolve_met_dir(config.met_dir))
    met_names = [m.name for m in met_files]

    # Prior: constant rate in CONTROL. Inferred: EMITIMES over the full run
    # span (zero-rate rows on spin-up / no-Q hours keep the timeline contiguous).
    control_prior = saturn_nestor.write_forward_control(
        start_utc, run_hours, config.prior_q_g_s * 3600.0, str(met_dir), met_names
    )
    q_full = pd.Series(np.nan, index=pd.date_range(start_utc, end_utc, freq="h"), dtype=float)
    q_full.loc[obs_hours] = inferred.set_index("hour_utc")["q_g_hr"].reindex(obs_hours).to_numpy()
    emitimes = saturn_nestor.write_emitimes(q_full)
    control_inferred = saturn_nestor.write_forward_control(
        start_utc, run_hours, 0.0, str(met_dir), met_names, use_emitimes=True
    )

    context.log.info(
        "forward prior run: %d h from %s at %.1f g/s", run_hours, start_utc, config.prior_q_g_s
    )
    res_prior = hysplit_exec.run_control(
        control_prior, saturn_nestor.setup_cfg(numpar=config.numpar)
    )
    grid_prior = saturn_nestor.parse_cdump(res_prior.cdump_path)

    context.log.info("forward inferred-Q run: EMITIMES with %d records", len(q_full))
    res_inferred = hysplit_exec.run_control(
        control_inferred,
        saturn_nestor.setup_cfg(numpar=config.numpar, use_emitimes=True),
        extra_files={"EMITIMES": emitimes},
    )
    grid_inferred = saturn_nestor.parse_cdump(res_inferred.cdump_path)

    pred_prior = _predictions_from_cdump(grid_prior, obs_hours, temps, config.cell_agg)
    pred_inferred = _predictions_from_cdump(grid_inferred, obs_hours, temps, config.cell_agg)
    metrics = {
        "prior": saturn_nestor.score(obs_ppb.to_numpy(), pred_prior.to_numpy()),
        "inferred": saturn_nestor.score(obs_ppb.to_numpy(), pred_inferred.to_numpy()),
    }
    predictions = pd.DataFrame(
        {
            "hour_utc": [h.isoformat() for h in obs_hours],
            "obs_ppb": obs_ppb.to_numpy(),
            "pred_prior_ppb": pred_prior.to_numpy(),
            "pred_inferred_ppb": pred_inferred.to_numpy(),
        },
    )

    tag = _tag(config)
    ok = inferred[inferred["flag"] == "ok"]
    summary_md = (
        f"# Saturn→Nestor HYSPLIT run `{tag}`\n\n"
        f"window: **{config.window_start} → {config.window_end}** | "
        f"hours_back={config.hours_back} | met={config.met_source} | "
        f"numpar={config.numpar}\n\n"
        f"Source: {saturn_nestor.SOURCE[0]} ({saturn_nestor.SOURCE[1]}, "
        f"{saturn_nestor.SOURCE[2]}) — the ONLY source in both directions.\n"
        f"Receptor: {saturn_nestor.RECEPTOR[0]} ({saturn_nestor.RECEPTOR[1]}, "
        f"{saturn_nestor.RECEPTOR[2]}).\n\n"
        f"## Back-calculated emission rate\n\n"
        f"valid hours: {len(ok)}/{len(inferred)} | "
        f"median Q: {ok['q_g_s'].median() if not ok.empty else float('nan'):.2f} g/s | "
        f"max Q: {ok['q_g_s'].max() if not ok.empty else float('nan'):.2f} g/s | "
        f"prior: {config.prior_q_g_s} g/s\n\n"
        f"flags: {inferred['flag'].value_counts().to_dict()}\n\n"
        f"## Forward verification at Nestor\n\n"
        f"prior-Q:    {metrics['prior']}\n\n"
        f"inferred-Q: {metrics['inferred']}\n\n"
        f"## Caveats\n\n"
        f"- Met is {config.met_source} — at ~880 m source–receptor separation the\n"
        f"  plume geometry is parameterized turbulence on a shared wind field;\n"
        f"  the inferred-Q forward run reuses the same met as the inversion, so\n"
        f"  its near-closure is a consistency check, not independent skill.\n"
        f"- Q(t) assumes constant emission over the trailing {config.hours_back} h\n"
        f"  window of each observation hour.\n"
        f"- below_floor hours mean the backward footprint never touched the\n"
        f"  Saturn cell (wind not from the source sector) — Q is undefined there,\n"
        f"  not zero. Wind direction is recorded alongside each hour.\n"
        f"- Spin-up hours before the window carry zero inferred emission.\n"
    )

    bucket = os.getenv("DAGSTER_S3_BUCKET")
    archived: dict[str, str] = {}
    if bucket:
        s3_client = s3.get_client()
        prefix = f"runs/hysplit/{tag}"

        def _put(key: str, body: bytes, label: str) -> None:
            s3_client.put_object(Bucket=bucket, Key=f"{prefix}/{key}", Body=body)
            archived[label] = f"{prefix}/{key}"

        buf = io.BytesIO()
        pd.DataFrame(saturn_backward_footprint["records"]).to_parquet(buf, index=False)
        _put("sensitivity.parquet", buf.getvalue(), "sensitivity")
        buf = io.BytesIO()
        inferred.assign(hour_utc=inferred["hour_utc"].astype(str)).to_parquet(buf, index=False)
        _put("inferred_emissions.parquet", buf.getvalue(), "inferred_emissions")
        buf = io.BytesIO()
        predictions.to_parquet(buf, index=False)
        _put("forward_predictions.parquet", buf.getvalue(), "forward_predictions")
        _put(
            "metrics.json",
            _json.dumps(
                {"tag": tag, "metrics": metrics, "config": dict(config)}, indent=2, default=str
            ).encode(),
            "metrics",
        )
        _put("summary.md", summary_md.encode(), "summary")
        for name, text in saturn_backward_footprint["controls"].items():
            s3_client.put_object(
                Bucket=bucket, Key=f"{prefix}/controls/{name}.txt", Body=text.encode()
            )
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/controls/forward_prior.txt",
            Body=control_prior.encode(),
        )
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/controls/forward_inferred.txt",
            Body=control_inferred.encode(),
        )
        s3_client.put_object(
            Bucket=bucket, Key=f"{prefix}/controls/EMITIMES.txt", Body=emitimes.encode()
        )
        archived["controls"] = f"{prefix}/controls/"
        for name, blob in saturn_backward_footprint["cdumps"].items():
            s3_client.put_object(Bucket=bucket, Key=f"{prefix}/cdumps/{name}.bin", Body=blob)
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/cdumps/forward_prior.bin",
            Body=res_prior.cdump_path.read_bytes(),
        )
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/cdumps/forward_inferred.bin",
            Body=res_inferred.cdump_path.read_bytes(),
        )
        archived["cdumps"] = f"{prefix}/cdumps/"

        manifest = RunManifest(
            kind="hysplit",
            tag=tag,
            window=[config.window_start, config.window_end],
            git_sha=os.getenv("DAGSTER_GIT_SHA", "unknown"),
            image_digest=os.getenv("DAGSTER_IMAGE_DIGEST", "unknown"),
            status="complete",
            created=datetime.now(UTC).isoformat(),
            skill={"validation": metrics["prior"]["corr"]},
            headline={
                "median_q_g_s": float(ok["q_g_s"].median()) if not ok.empty else None,
                "prior_corr": metrics["prior"]["corr"],
                "inferred_corr": metrics["inferred"]["corr"],
            },
            artifacts=archived,
        )
        write_manifest(s3_client, bucket, manifest)
    else:
        log.info("DAGSTER_S3_BUCKET unset; skipping archival write to runs/hysplit/%s/", tag)

    return dg.MaterializeResult(
        value={
            "tag": tag,
            "metrics": metrics,
            "predictions": predictions.to_dict(orient="records"),
            "archived": archived,
        },
        metadata={
            "tag": tag,
            "prior_corr": metrics["prior"]["corr"],
            "prior_rms": metrics["prior"]["rms"],
            "prior_peak_ratio": metrics["prior"]["peak_ratio"],
            "inferred_corr": metrics["inferred"]["corr"],
            "inferred_rms": metrics["inferred"]["rms"],
            "inferred_peak_ratio": metrics["inferred"]["peak_ratio"],
            "summary": dg.MetadataValue.md(summary_md),
            "archived_snapshot": dg.MetadataValue.md(
                "\n".join(f"- `{k}`: `{v}`" for k, v in archived.items()) or "(no S3 archive)",
            ),
        },
    )


saturn_nestor_job = dg.define_asset_job(
    name="saturn_nestor_job",
    selection=dg.AssetSelection.assets(
        "saturn_backward_footprint",
        "saturn_inferred_emissions",
        "saturn_forward_verification",
    ),
)
