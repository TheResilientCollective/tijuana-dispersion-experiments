"""Sobol sensitivity — science core (issue #2).

This module is the pure, framework-agnostic science for the first NRP
workload. It is imported by the Dagster pipeline (``dagster_pipeline.py``)
and by the local prototype/tests; it has no Dagster dependency so it can
be unit-tested and run on a worker pod without an orchestrator.

Refactored from the local prototype
``experiments/2026-05-05_sensitivity_lhs/run.py``. The science is
identical to that 200-sample LHS run; here we use a proper SALib Sobol
sample (first-order S1 + total-order ST) instead of a Pearson proxy,
and the sample matrix is split into chunks so independent workers can
each evaluate a slice.

Hard rule (AGENTS.md): never fabricate data. If the H2S parquet is
missing the loader raises — it does not synthesise observations.

Import contract: the ``tijuana_dispersion`` service package is a
*deferred* dependency. It lives behind the opt-in ``service`` extra
(local dev / the NRP worker image) and is **not** installed in this
repo's CI (`uv sync --extra dev`). So it is imported lazily, inside
the only functions that actually run the forward model
(``make_drivers_and_met``, ``evaluate_sample``). The pure-science
surface — problem definition, Saltelli sampling, chunking,
reassembly, SALib analysis — imports clean and is unit-tested in CI
without the service. ``dg list defs`` likewise works service-free.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from SALib.analyze import sobol as sobol_analyze
from SALib.sample import sobol as sobol_sample

if TYPE_CHECKING:
    # Type-only; never imported at runtime (see "Import contract").
    from tijuana_dispersion import MetSpec, ReceptorSpec
    from tijuana_dispersion.emissions import EmissionDrivers, SourceSpecLocation

log = logging.getLogger(__name__)

# Default fit window (matches the prototype). Override via SobolConfig.
DEFAULT_WINDOW = ("2026-03-13", "2026-03-16")

# Repo-relative default for the H2S parquet. On NRP the worker image bakes
# the data in or fetches it; locally it is data/modeldata_h2s_nofill.parquet.
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARQUET = _REPO_ROOT / "data" / "modeldata_h2s_nofill.parquet"

# Plain data (no service types) so the module imports without the
# ``service`` extra. The typed ``ReceptorSpec`` / ``SourceSpecLocation``
# objects are built lazily by ``_receptors()`` / ``_locations()``.
_RECEPTOR_DEFS: list[tuple[str, float, float]] = [
    ("SAN YSIDRO", 32.552794, -117.047286),
    ("NESTOR - BES", 32.567097, -117.090656),
    ("IB CIVIC CTR", 32.576139, -117.115361),
]
RECEPTOR_NAMES: list[str] = [name for name, _, _ in _RECEPTOR_DEFS]

_LOCATION_DEFS: list[tuple[str, float, float, str]] = [
    ("Stewart's Drain", 32.54064, -117.05801, "drain"),
    ("Smuggler's Gulch", 32.5377, -117.08623, "drain"),
    ("Hollister St PS", 32.5476, -117.088374, "drain"),
    ("Goat Canyon", 32.5369, -117.09916, "drain"),
    ("Goat Canyon PS", 32.543476, -117.108026, "drain"),
    ("Del Sol Canyon", 32.5393, -117.06885, "drain"),
    ("Silva Drain", 32.539743, -117.064269, "drain"),
    ("Saturn Blvd Bridge", 32.559383, -117.092992, "channel"),
    ("Hollister St Bridge N", 32.554177, -117.084135, "channel"),
    ("Hollister St Bridge S", 32.551466, -117.084021, "channel"),
    ("Dairy Mart Bridge", 32.548531, -117.064293, "channel"),
    ("Oneonta Slough", 32.570082, -117.126724, "estuary"),
    ("Beach Outlet", 32.556206, -117.126178, "estuary"),
    ("CDLP W", 32.542103, -117.054117, "channel"),
    ("CDLP E", 32.542166, -117.050325, "channel"),
    ("Otay Pond", 32.594557, -117.113542, "bay"),
    ("Fruitdale Pond", 32.595305, -117.091869, "bay"),
]


def _receptors() -> list[ReceptorSpec]:
    """Build the typed receptor specs (lazy — needs the service extra)."""
    from tijuana_dispersion import ReceptorSpec

    return [ReceptorSpec(name=n, lat=la, lon=lo) for n, la, lo in _RECEPTOR_DEFS]


def _locations() -> list[SourceSpecLocation]:
    """Build the typed source locations (lazy — needs the service extra)."""
    from tijuana_dispersion.emissions import SourceSpecLocation

    return [SourceSpecLocation(n, la, lo, a) for n, la, lo, a in _LOCATION_DEFS]


# 11 parameters, physically-motivated bounds (identical to the prototype).
PARAM_RANGES: dict[str, tuple[float, float]] = {
    "baseline_scale": (1.0, 200.0),
    "Q10": (1.5, 3.5),
    "T_ref_c": (10.0, 30.0),
    "substrate_alpha": (0.0, 0.5),
    "substrate_threshold": (10.0, 40.0),
    "diel_amplitude": (1.0, 5.0),
    "diel_phase_hours": (0.0, 12.0),
    "f_arch_drain": (0.5, 5.0),
    "f_arch_channel": (0.1, 2.0),
    "f_arch_estuary": (0.1, 3.0),
    "f_arch_bay": (0.0, 0.5),
}

# Scalar fit metrics fed to Sobol analysis: 3 receptors × 3 metrics = 9.
METRIC_KINDS: tuple[str, ...] = ("rms", "corr", "peak_ratio")
OUTPUT_COLUMNS: list[str] = [f"{kind}__{name}" for name in RECEPTOR_NAMES for kind in METRIC_KINDS]


def build_problem() -> dict[str, Any]:
    """SALib problem definition for the 11 emission parameters."""
    names = list(PARAM_RANGES)
    return {
        "num_vars": len(names),
        "names": names,
        "bounds": [list(PARAM_RANGES[n]) for n in names],
    }


def build_samples(n_base: int, seed: int = 42) -> np.ndarray:
    """Full Saltelli sample matrix, deterministic for a given (n_base, seed).

    Parameters
    ----------
    n_base : int
        Base sample size ``N``. SALib produces ``N * (D + 2)`` rows for
        ``D`` parameters with ``calc_second_order=False``.
    seed : int, optional
        Sobol-sequence seed; fixes the matrix so chunk workers and the
        aggregator generate the *same* matrix independently.

    Returns
    -------
    np.ndarray
        Shape ``(N * (D + 2), D)``.

    """
    return sobol_sample.sample(build_problem(), n_base, calc_second_order=False, seed=seed)


def chunk_bounds(n_rows: int, n_chunks: int) -> list[tuple[int, int]]:
    """Contiguous [start, end) row slices, one per chunk, covering all rows.

    Uses ``np.array_split`` semantics so any ``n_rows`` divides cleanly
    across ``n_chunks`` (last chunks may be one row smaller).
    """
    edges = np.array_split(np.arange(n_rows), n_chunks)
    return [(int(e[0]), int(e[-1]) + 1) if len(e) else (0, 0) for e in edges]


# ---------- data loading (no synthetic fallback) ---------- #


def load_window(parquet_path: Path, window: tuple[str, str]) -> pd.DataFrame:
    """Load + hour-aggregate the H2S parquet for the fit window.

    Raises
    ------
    FileNotFoundError
        If the parquet is absent. Per AGENTS.md we never substitute
        synthetic data when the real input is missing.

    """
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"H2S data not found at {parquet_path}. Run "
            "`python scripts/fetch_data.py --only modeldata_h2s_nofill` "
            "(local) or bake it into the worker image (NRP). Refusing to "
            "fabricate observations.",
        )
    df = pd.read_parquet(parquet_path)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    start = pd.Timestamp(window[0]).tz_localize("America/Los_Angeles")
    end = pd.Timestamp(window[1]).tz_localize("America/Los_Angeles")
    df = df[(df["time"] >= start) & (df["time"] < end)].copy()
    if df.empty:
        raise ValueError(f"No H2S rows in window {window}; check the parquet coverage.")
    df["hour"] = df["time"].dt.floor("h")
    df["is_night_f"] = (df["day_night"] == "night").astype(float)
    cols = [
        "hour",
        "site_name",
        "H2S",
        "wind_speed_10m",
        "wind_direction_10m",
        "temperature_2m",
        "cloud_cover",
        "is_night_f",
        "sbiwtp_flow_mgd",
        "sbiwtp_deficit",
        "tide_height",
    ]
    return df[cols].groupby(["hour", "site_name"], as_index=False).mean(numeric_only=True)


def make_drivers_and_met(
    df_window: pd.DataFrame,
) -> tuple[list[EmissionDrivers], list[MetSpec], pd.DatetimeIndex]:
    """Build the per-hour driver + met series from the NESTOR/Berry record."""
    from tijuana_dispersion import MetSpec
    from tijuana_dispersion.emissions import EmissionDrivers

    nestor = df_window[df_window["site_name"] == "NESTOR - BES"].sort_values("hour")
    drivers: list[EmissionDrivers] = []
    met: list[MetSpec] = []
    hours: list[pd.Timestamp] = []
    for _, row in nestor.iterrows():
        if pd.isna(row["wind_speed_10m"]) or pd.isna(row["wind_direction_10m"]):
            continue
        is_night = bool(row["is_night_f"] >= 0.5) if pd.notna(row["is_night_f"]) else False
        drivers.append(
            EmissionDrivers(
                timestamp=row["hour"].isoformat(),
                temperature_c=float(row["temperature_2m"]),
                wind_speed_10m_ms=float(row["wind_speed_10m"]),
                sbiwtp_flow_mgd=float(row["sbiwtp_flow_mgd"])
                if pd.notna(row["sbiwtp_flow_mgd"])
                else 0.0,
                sbiwtp_deficit=float(row["sbiwtp_deficit"])
                if pd.notna(row["sbiwtp_deficit"])
                else 0.0,
                tide_height_m=float(row["tide_height"]) if pd.notna(row["tide_height"]) else 0.0,
                is_night=is_night,
            ),
        )
        met.append(
            MetSpec(
                timestamp=row["hour"].isoformat(),
                wind_speed_ms=float(row["wind_speed_10m"]),
                wind_direction_deg=float(row["wind_direction_10m"]),
                temperature_c=float(row["temperature_2m"]),
                cloud_cover_frac=float(row["cloud_cover"]) / 100.0
                if pd.notna(row["cloud_cover"])
                else 0.5,
                is_night=is_night,
            ),
        )
        hours.append(row["hour"])
    return drivers, met, pd.DatetimeIndex(hours)


def build_obs(df_window: pd.DataFrame, hours: pd.DatetimeIndex, names: list[str]) -> np.ndarray:
    """(n_hours, n_receptors) observed H2S; NaN where missing."""
    obs = np.full((len(hours), len(names)), np.nan)
    for r_idx, n in enumerate(names):
        sub = df_window[df_window["site_name"] == n].set_index("hour")["H2S"]
        for h_idx, h in enumerate(hours):
            if h in sub.index and pd.notna(sub.loc[h]):
                obs[h_idx, r_idx] = float(sub.loc[h])
    return obs


def evaluate_sample(
    sample_row: np.ndarray,
    param_names: list[str],
    drivers: list[EmissionDrivers],
    met: list[MetSpec],
    obs: np.ndarray,
) -> dict[str, float]:
    """Evaluate one parameter vector → the 9 scalar fit metrics.

    Mirrors the prototype's ``evaluate_one``; uses the published
    ``tijuana_dispersion`` forward model through the service request
    object so the science is identical to the calibration line. The
    service import is lazy (deferred ``service`` extra).
    """
    from tijuana_dispersion import (
        EmissionParameters,
        EmissionsModel,
        ForwardRunRequest,
        SourceSpec,
        run_forward,
    )

    receptors = _receptors()
    locations = _locations()
    s = dict(zip(param_names, sample_row, strict=True))
    params = EmissionParameters(
        Q10=s["Q10"],
        T_ref_c=s["T_ref_c"],
        substrate_alpha=s["substrate_alpha"],
        substrate_threshold_mgd=s["substrate_threshold"],
        diel_amplitude=s["diel_amplitude"],
        diel_phase_hours=s["diel_phase_hours"],
        f_arch={
            "drain": s["f_arch_drain"],
            "channel": s["f_arch_channel"],
            "estuary": s["f_arch_estuary"],
            "bay": s["f_arch_bay"],
            "spill": 1.0,
        },
        baselines_g_s={loc.name: s["baseline_scale"] for loc in locations},
    )
    em = EmissionsModel(params)

    n_t = len(drivers)
    pred = np.zeros((n_t, len(receptors)))
    for t_idx, drv in enumerate(drivers):
        sources = [
            SourceSpec(
                name=loc.name,
                lat=loc.lat,
                lon=loc.lon,
                emission_rate_g_s=em.emission_rate_g_s(loc, drv),
                height_m=loc.height_m,
                archetype=loc.archetype,
            )
            for loc in locations
        ]
        res = run_forward(
            ForwardRunRequest(
                sources=sources,
                receptors=receptors,
                meteorology=[met[t_idx]],
                units="ppb",
            ),
        )
        pred[t_idx] = np.asarray(res.concentrations)[0]

    out: dict[str, float] = {}
    for r_idx, name in enumerate(RECEPTOR_NAMES):
        valid = ~np.isnan(obs[:, r_idx])
        if valid.sum() < 5:
            # Not enough obs to score this receptor in this window: emit
            # neutral values so the Sobol matrix stays rectangular. (This
            # is a metric-coverage gap, not fabricated observation data.)
            out[f"rms__{name}"] = float("nan")
            out[f"corr__{name}"] = 0.0
            out[f"peak_ratio__{name}"] = 0.0
            continue
        o = obs[valid, r_idx]
        p = pred[valid, r_idx]
        out[f"rms__{name}"] = float(np.sqrt(np.mean((o - p) ** 2)))
        out[f"corr__{name}"] = float(np.corrcoef(o, p)[0, 1]) if p.std() > 0 else 0.0
        out[f"peak_ratio__{name}"] = float(p.max() / (o.max() + 1e-6))
    return out


def reassemble(chunks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Reassemble per-chunk outputs into dense, ordered metric vectors.

    Parameters
    ----------
    chunks : dict
        ``{partition_key: chunk_value}`` where each ``chunk_value`` is the
        dict produced by ``sobol_chunk_results`` (keys: ``start``, ``end``,
        ``param_names``, ``metric_columns``, ``rows``).

    Returns
    -------
    dict
        ``{"param_names", "metric_columns", "y_by_metric", "n_samples"}``.
        ``y_by_metric`` maps each metric column to a dense ``(total,)``
        array in exact Saltelli row order.

    Raises
    ------
    ValueError
        If no samples are present, or the reassembled matrix has gaps —
        a partial matrix would make the Sobol analysis silently invalid.

    """
    non_empty = [c for c in chunks.values() if c.get("rows")]
    if not non_empty:
        raise ValueError("No Sobol samples across any chunk — nothing to analyse.")
    param_names = non_empty[0]["param_names"]
    metric_columns = non_empty[0]["metric_columns"]
    total = max(int(c["end"]) for c in chunks.values())

    y_by_metric = {m: np.full(total, np.nan) for m in metric_columns}
    filled = np.zeros(total, dtype=bool)
    for c in non_empty:
        for row in c["rows"]:
            gi = int(row["_row"])
            filled[gi] = True
            for m in metric_columns:
                y_by_metric[m][gi] = row[m]
    if not filled.all():
        missing = int((~filled).sum())
        raise ValueError(
            f"Sobol matrix incomplete: {missing}/{total} sample rows missing — "
            "a partial matrix yields an invalid Sobol analysis. Ensure all "
            "sobol_chunk_results partitions materialised.",
        )
    return {
        "param_names": param_names,
        "metric_columns": metric_columns,
        "y_by_metric": y_by_metric,
        "n_samples": int(filled.sum()),
    }


def analyze(problem: dict[str, Any], y: np.ndarray) -> pd.DataFrame:
    """Run SALib Sobol on one output column, return a tidy frame.

    ``y`` is the (n_samples,) vector for a single metric column, ordered
    exactly as ``build_samples`` produced the rows.
    """
    res = sobol_analyze.analyze(problem, y, calc_second_order=False, print_to_console=False)
    return pd.DataFrame(
        {
            "parameter": problem["names"],
            "S1": res["S1"],
            "S1_conf": res["S1_conf"],
            "ST": res["ST"],
            "ST_conf": res["ST_conf"],
        },
    )


# ---------- post-analysis helpers (pure; CI-testable) ---------- #
#
# These are the diagnostics + summaries the operator wants AT THE END
# of every NRP Sobol run (rather than running them by hand against the
# bucket each time). The Dagster `sobol_post_analysis` asset glues
# these into the pipeline; nothing here imports Dagster, so they are
# unit-tested without the service or the orchestrator.


def convergence_diagnostics(indices: pd.DataFrame) -> dict[str, Any]:
    """Convergence telemetry — would have caught the smoke-as-real bug.

    Computes the headline diagnostics for an indices table:
    - ``ST_conf / |ST|`` median + p90 (the standard "is it converged?"
      ratio; conventional acceptance threshold is < 0.20 median).
    - count of rows with ``S1 < -0.01`` (true S1 ≥ 0 by definition;
      strongly-negative values are the small-sample Saltelli noise
      signature).
    - ``is_converged`` heuristic: median ratio < 0.20 AND zero
      strongly-negative S1.

    Reasonable expectations: at N=8192 we observe median ≈ 0.15,
    zero negatives; at N≈23 (smoke) median ≈ 1.5, ~40 % negative.
    """
    if indices.empty:
        return {"n_rows": 0, "is_converged": False}
    ratio = indices["ST_conf"].abs() / indices["ST"].abs().clip(lower=1e-9)
    neg_s1 = int((indices["S1"] < -0.01).sum())
    median_ratio = float(ratio.median())
    return {
        "n_rows": len(indices),
        "st_conf_over_st_median": round(median_ratio, 4),
        "st_conf_over_st_p90": round(float(ratio.quantile(0.9)), 4),
        "rows_with_negative_s1": neg_s1,
        "max_st_conf": round(float(indices["ST_conf"].max()), 4),
        "is_converged": bool(median_ratio < 0.20 and neg_s1 == 0),
    }


def global_ranking(indices: pd.DataFrame) -> pd.DataFrame:
    """Per-parameter ranking aggregated across all metric columns.

    Returns columns ``mean_ST, median_ST, max_ST, mean_S1``, sorted
    descending by ``mean_ST``. Use ``mean_ST`` for a "broad
    importance" view (smooths receptor- and metric-specific
    sensitivities) and ``max_ST`` to surface parameters that matter
    *somewhere* even if they're inert globally.
    """
    g = (
        indices.groupby("parameter")
        .agg(
            mean_ST=("ST", "mean"),
            median_ST=("ST", "median"),
            max_ST=("ST", "max"),
            mean_S1=("S1", "mean"),
        )
        .sort_values("mean_ST", ascending=False)
        .reset_index()
    )
    return g


def top_n_per_metric(indices: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Top-``n`` parameters by ``ST`` for each metric column.

    Long-form output ``(metric, rank, parameter, S1, ST, ST_conf)``
    suitable for direct UI rendering or markdown dumping.
    """
    rows: list[dict[str, Any]] = []
    for m, sub in indices.groupby("metric", sort=True):
        top = sub.sort_values("ST", ascending=False).head(n)
        for rank, (_, r) in enumerate(top.iterrows(), start=1):
            rows.append(
                {
                    "metric": m,
                    "rank": rank,
                    "parameter": r["parameter"],
                    "S1": float(r["S1"]),
                    "ST": float(r["ST"]),
                    "ST_conf": float(r["ST_conf"]),
                },
            )
    return pd.DataFrame(rows)


def magnitude_vs_shape_split(indices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split the metric kinds into magnitude (rms/peak_ratio) vs shape
    (corr) and rank parameters in each group.

    Captures the canonical decomposition the calibration arc surfaced:
    magnitude fit is interaction-dominated by ``substrate_threshold``
    + ``baseline_scale`` + ``T_ref_c``; shape fit is dominated by
    ``diel_phase_hours`` largely first-order. Returns
    ``{"magnitude": …, "shape": …}`` each a global_ranking-shaped frame.
    """
    is_mag = indices["metric"].str.startswith(("rms__", "peak_ratio__"))
    return {
        "magnitude": global_ranking(indices[is_mag]),
        "shape": global_ranking(indices[~is_mag]),
    }


def interaction_table(indices: pd.DataFrame, min_interaction: float = 0.10) -> pd.DataFrame:
    """Rows where the interaction-mediated effect (``ST - S1``) is
    materially large. These are parameters whose univariate
    correlation (which is all a Pearson/LHS proxy can see) understates
    their true variance contribution.

    The N=8192 NRP run found ``substrate_threshold`` with
    ``ST - S1 ≈ 0.30`` at every magnitude metric — that's the canonical
    example of the LHS-Pearson 3× underestimate.
    """
    df = indices.assign(interaction=indices["ST"] - indices["S1"])
    return (
        df[df["interaction"] > min_interaction]
        .sort_values("interaction", ascending=False)
        .reset_index(drop=True)
    )


def dropout_candidates(indices: pd.DataFrame, max_st_threshold: float = 0.02) -> list[str]:
    """Parameters whose ``max ST`` across all metrics is below the
    threshold — i.e. they don't influence ANY fit metric at any
    receptor IN THIS WINDOW.

    Reported only as candidates: a single-window Sobol cannot
    establish global inertness. ``f_arch_bay`` was flagged here at
    N=8192 on the Mar 13-15 window (max ST ≈ 5e-6) but should be
    re-checked across other windows / regimes before being permanently
    removed from the calibration parameter set.
    """
    if indices.empty:
        return []
    max_st = indices.groupby("parameter")["ST"].max()
    return sorted(max_st[max_st < max_st_threshold].index.tolist())


@dataclass(frozen=True)
class Window:
    """One fit window for a Sobol sweep."""

    start: str
    end: str
    note: str = ""


def load_windows(path: Path) -> list[Window]:
    """Parse + validate a bulk-windows YAML file (consumed by
    ``submit_sobol.py --windows-file``).

    Schema::

        windows:
          - { start: "YYYY-MM-DD", end: "YYYY-MM-DD", note?: "..." }
          - ...

    Raises ``ValueError`` on any schema violation so the submitter
    fails loudly before launching anything.
    """
    import yaml

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict) or "windows" not in raw:
        raise ValueError(f"{path}: top-level must be a mapping with a 'windows' list")
    wlist = raw["windows"]
    if not isinstance(wlist, list) or not wlist:
        raise ValueError(f"{path}: 'windows' must be a non-empty list")
    out: list[Window] = []
    for i, w in enumerate(wlist):
        if not isinstance(w, dict):
            raise ValueError(f"{path}: windows[{i}] must be a mapping; got {type(w).__name__}")
        if "start" not in w or "end" not in w:
            raise ValueError(f"{path}: windows[{i}] missing 'start' and/or 'end'")
        out.append(Window(start=str(w["start"]), end=str(w["end"]), note=str(w.get("note", ""))))
    return out


def run_tag(
    window_start: str,
    window_end: str,
    n_base_samples: int,
    seed: int,
    run_date: str | None = None,
) -> str:
    """Deterministic, human-readable archival tag.

    Returns e.g. ``2026-03-13_2026-03-16_N8192_seed42_2026-05-22``.
    Used to scope a run's archival snapshot under
    ``s3://<bucket>/runs/{tag}/...`` (separate from the IO-manager's
    asset-keyed "latest run" pointer at ``dagster/runs/...``), so
    multi-window / multi-seed studies don't overwrite each other.
    """
    if run_date is None:
        from datetime import UTC, datetime

        run_date = datetime.now(UTC).date().isoformat()
    return f"{window_start}_{window_end}_N{n_base_samples}_seed{seed}_{run_date}"
