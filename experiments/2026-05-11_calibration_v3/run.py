"""
calibration v3 — diurnal modifier on emissions.

Inputs:
    config.yaml                          (this folder)
    ../../data/modeldata_h2s_nofill.parquet   (fetched via scripts/fetch_data.py)

Outputs (gitignored output/ dir):
    fitted_rates_v2.csv      per-source rates from the v2 (no-diel) refit
    fitted_rates_v3.csv      per-source rates from the v3 (diel) fit
    timeseries_train.csv     obs + v2 pred + v3 pred per hour per receptor (train)
    timeseries_holdout.csv   same on the holdout window
    wind_residuals_v2.csv    wind-conditional residuals for v2 on holdout
    wind_residuals_v3.csv    wind-conditional residuals for v3 on holdout
    summary.json             per-receptor metrics for v2 and v3, train + holdout

Calibration design:
    - The forward model is c(t,r) = Σ_s [E_s × d(t)] × G(s,r,t) where
      d(t) = 1 + 0.5 × (diel_amplitude - 1) × (1 + cos(2π × (h - phase) / 24))
      is the diel multiplier (matches `tijuana_dispersion.f_diel`).
    - Linear in {E_s} for fixed (diel_amplitude, diel_phase_hours).
    - Outer loop (scipy.optimize.minimize, Nelder-Mead) searches the two
      diel params. Inner step is bounded NNLS on baselines via
      scipy.optimize.lsq_linear with archetype-derived upper bounds and a
      ridge toward archetype priors — same regularization as v2.

CLI:
    uv run python run.py             full train (Feb-Mar) + holdout (Apr 1-14)
    uv run python run.py --quick     Mar 13-15 only; ~30 s smoke test
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import lsq_linear, minimize
from tijuana_dispersion import (
    ARCHETYPE_BOUNDS_G_S,
    ARCHETYPE_PRIOR_G_S,
    MetCondition,
    Receptor,
    Source,
    SourceSpec,
    distributed_area_sources,
    distributed_channel_sources,
    forward_run_per_source,
    wind_conditional_residuals,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HERE = Path(__file__).parent
OUTPUTS = HERE / "output"


# ---------- named sources (Tier 1, unchanged from v2) ---------- #

NAMED_SOURCES: list[SourceSpec] = [
    SourceSpec(
        name="Stewart's Drain",
        lat=32.54064,
        lon=-117.05801,
        archetype="drain",
        emission_rate_g_s=0.5,
        height_m=1.0,
    ),
    SourceSpec(
        name="Smuggler's Gulch",
        lat=32.5377,
        lon=-117.08623,
        archetype="drain",
        emission_rate_g_s=0.5,
        height_m=1.0,
    ),
    SourceSpec(
        name="Hollister St PS",
        lat=32.5476,
        lon=-117.088374,
        archetype="drain",
        emission_rate_g_s=0.3,
        height_m=1.0,
    ),
    SourceSpec(
        name="Goat Canyon",
        lat=32.5369,
        lon=-117.09916,
        archetype="drain",
        emission_rate_g_s=0.3,
        height_m=1.0,
    ),
    SourceSpec(
        name="Goat Canyon PS",
        lat=32.543476,
        lon=-117.108026,
        archetype="drain",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Del Sol Canyon",
        lat=32.5393,
        lon=-117.06885,
        archetype="drain",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Silva Drain",
        lat=32.539743,
        lon=-117.064269,
        archetype="drain",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Saturn Blvd Bridge",
        lat=32.559383,
        lon=-117.092992,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Hollister St Bridge N",
        lat=32.554177,
        lon=-117.084135,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Hollister St Bridge S",
        lat=32.551466,
        lon=-117.084021,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Dairy Mart Bridge",
        lat=32.548531,
        lon=-117.064293,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Oneonta Slough Near IB",
        lat=32.570082,
        lon=-117.126724,
        archetype="estuary",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Tijuana River Beach Outlet",
        lat=32.556206,
        lon=-117.126178,
        archetype="estuary",
        emission_rate_g_s=0.3,
        height_m=1.0,
    ),
    SourceSpec(
        name="Tijuana River Crossing CDLP W",
        lat=32.542103,
        lon=-117.054117,
        archetype="channel",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Tijuana River Crossing CDLP E",
        lat=32.542166,
        lon=-117.050325,
        archetype="channel",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="San Diego Bay ponds Otay River Outlet",
        lat=32.594557,
        lon=-117.113542,
        archetype="bay",
        emission_rate_g_s=0.05,
        height_m=1.0,
    ),
    SourceSpec(
        name="San Diego Bay Ponds near Fruitdale",
        lat=32.595305,
        lon=-117.091869,
        archetype="bay",
        emission_rate_g_s=0.05,
        height_m=1.0,
    ),
]

RECEPTOR_COORDS: dict[str, tuple[float, float]] = {
    "SAN YSIDRO": (32.552794, -117.047286),
    "NESTOR - BES": (32.567097, -117.090656),
    "IB CIVIC CTR": (32.576139, -117.115361),
}


# ---------- config and data ---------- #


def load_config() -> dict[str, Any]:
    with (HERE / "config.yaml").open() as f:
        return yaml.safe_load(f)


def load_window(parquet_path: Path, start: str, end: str) -> pd.DataFrame:
    df = pd.read_parquet(parquet_path)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    start_ts = pd.Timestamp(start).tz_localize("America/Los_Angeles")
    end_ts = pd.Timestamp(end).tz_localize("America/Los_Angeles")
    mask = (df["time"] >= start_ts) & (df["time"] < end_ts)
    return df.loc[mask].copy()


def build_source_field(config: dict[str, Any]) -> list[SourceSpec]:
    sc = config["sources"]["channel"]
    se = config["sources"]["estuary_grid"]
    channel = distributed_channel_sources(
        start_lat=sc["start_lat"],
        start_lon=sc["start_lon"],
        end_lat=sc["end_lat"],
        end_lon=sc["end_lon"],
        n_sources=sc["n_sources"],
        archetype="channel",
        seed_rate_g_s=sc["seed_rate_g_s"],
        name_prefix="channel",
    )
    estuary = distributed_area_sources(
        bounding_box=tuple(se["bbox"]),
        nx=se["nx"],
        ny=se["ny"],
        archetype="estuary",
        seed_rate_g_s=se["seed_rate_g_s"],
        name_prefix="estuary",
    )
    return NAMED_SOURCES + channel + estuary


def build_met_and_obs(
    df: pd.DataFrame, receptor_names: list[str]
) -> tuple[list[MetCondition], np.ndarray, pd.DatetimeIndex]:
    """Hourly grid: pivot obs to (n_hours × n_receptors); met taken from NESTOR site."""
    df = df.copy()
    df["hour"] = df["time"].dt.floor("h")
    # `day_night` arrives as 'day'/'night' strings; convert to a float before agg.
    df["is_night_f"] = (df["day_night"] == "night").astype(float)
    grouped = df.groupby(["hour", "site_name"], as_index=False).agg(
        {
            "H2S": "mean",
            "wind_speed_10m": "mean",
            "wind_direction_10m": "mean",
            "temperature_2m": "mean",
            "cloud_cover": "mean",
            "is_night_f": "mean",
        }
    )
    # Met from NESTOR (most complete record); fall back to any-site mean if missing
    nestor = grouped[grouped["site_name"] == "NESTOR - BES"].set_index("hour").sort_index()
    if nestor.empty:
        raise ValueError("no NESTOR records in this window — can't build met series")

    valid_hours = nestor.dropna(subset=["wind_speed_10m", "wind_direction_10m"]).index
    met: list[MetCondition] = []
    for h in valid_hours:
        row = nestor.loc[h]
        cloud = row["cloud_cover"]
        cloud_frac = float(cloud) / 100.0 if pd.notna(cloud) else 0.5
        is_night_v = row["is_night_f"]
        is_night = bool(is_night_v >= 0.5) if pd.notna(is_night_v) else False
        met.append(
            MetCondition(
                timestamp=h.isoformat(),
                wind_speed_ms=float(row["wind_speed_10m"]),
                wind_direction_deg=float(row["wind_direction_10m"]),
                temperature_c=float(row["temperature_2m"])
                if pd.notna(row["temperature_2m"])
                else 17.0,
                cloud_cover_frac=cloud_frac,
                is_night=is_night,
            )
        )

    obs = np.full((len(valid_hours), len(receptor_names)), np.nan)
    for r_idx, rname in enumerate(receptor_names):
        sub = grouped[grouped["site_name"] == rname].set_index("hour")["H2S"]
        for h_idx, h in enumerate(valid_hours):
            if h in sub.index and pd.notna(sub.loc[h]):
                obs[h_idx, r_idx] = float(sub.loc[h])
    return met, obs, valid_hours


# ---------- diel multiplier ---------- #


def diel_multiplier(timestamps: list[str], amplitude: float, phase_hours: float) -> np.ndarray:
    """Hourly diel multiplier d(t), shape (n_t,).

    d(t) = 1 + 0.5 × (amplitude - 1) × (1 + cos(2π × (h - phase) / 24))

    At h = phase: d = amplitude (peak — nocturnal by default).
    12 hours later: d = 2 - amplitude (daytime trough; clamped to ≥ 0 for safety).
    """
    hours = np.empty(len(timestamps))
    for i, ts in enumerate(timestamps):
        # Parse: '2026-03-14T03:00:00-08:00' → 3.0
        try:
            t = pd.Timestamp(ts)
            hours[i] = t.hour + t.minute / 60.0
        except (ValueError, TypeError):
            hours[i] = 12.0
    angle = 2 * math.pi * (hours - phase_hours) / 24.0
    d = 1.0 + 0.5 * (amplitude - 1.0) * (1.0 + np.cos(angle))
    return np.maximum(d, 0.05)  # never push fully to zero — keep some signal


# ---------- bounded NNLS inner step (mirrors run_inversion_bounded but on a precomputed A_full) ---------- #


def solve_bounded(
    a_full: np.ndarray,  # (n_t, n_r, n_s) per-source unit-rate footprints
    obs: np.ndarray,  # (n_t, n_r) observations (may contain NaN)
    sources: list[SourceSpec],
    prior_lambda: float,
    smoothness_lambda: float,
    diel: np.ndarray | None = None,  # (n_t,) per-hour diel multiplier or None
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (fitted_rates, predictions, rms_ppb). predictions has shape (n_t, n_r)."""
    n_s = a_full.shape[2]
    a_mod = a_full if diel is None else diel[:, None, None] * a_full

    valid = ~np.isnan(obs)
    a = a_mod[valid]  # (n_valid, n_s)
    b = obs[valid]  # (n_valid,)

    bounds_upper = np.array(
        [ARCHETYPE_BOUNDS_G_S.get(s.archetype, ARCHETYPE_BOUNDS_G_S["unknown"]) for s in sources]
    )
    prior_mean = np.array(
        [ARCHETYPE_PRIOR_G_S.get(s.archetype, ARCHETYPE_PRIOR_G_S["unknown"]) for s in sources]
    )

    if prior_lambda > 0:
        a = np.vstack([a, prior_lambda * np.eye(n_s)])
        b = np.concatenate([b, prior_lambda * prior_mean])

    if smoothness_lambda > 0:
        # First-difference within name-prefix groups (e.g. channel_00 ↔ channel_01)
        prefixes = []
        for s in sources:
            parts = s.name.rsplit("_", 1)
            prefixes.append(parts[0] if len(parts) == 2 and parts[1].isdigit() else None)
        l_rows = []
        for i in range(n_s - 1):
            if prefixes[i] is not None and prefixes[i] == prefixes[i + 1]:
                row = np.zeros(n_s)
                row[i] = smoothness_lambda
                row[i + 1] = -smoothness_lambda
                l_rows.append(row)
        if l_rows:
            a = np.vstack([a, np.array(l_rows)])
            b = np.concatenate([b, np.zeros(len(l_rows))])

    res = lsq_linear(a, b, bounds=(0.0, bounds_upper), method="trf", max_iter=2000)
    rates = res.x
    pred = a_mod @ rates  # (n_t, n_r)
    rms = float(np.sqrt(np.nanmean((obs - pred) ** 2)))
    return rates, pred, rms


# ---------- v3 outer optimization ---------- #


def weighted_log_mse(pred: np.ndarray, obs: np.ndarray) -> float:
    """log10(1 + (pred - obs)^2) averaged over valid (t, r). Squelches the impact
    of the few extreme spill-event hours while still penalising widespread bias."""
    valid = ~np.isnan(obs)
    sq = (pred[valid] - obs[valid]) ** 2
    return float(np.mean(np.log10(1.0 + sq)))


def fit_v3(
    a_full: np.ndarray,
    obs: np.ndarray,
    timestamps: list[str],
    sources: list[SourceSpec],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Outer optimization over (diel_amplitude, diel_phase_hours)."""
    outer = config["calibration"]["outer"]
    amp_lo, amp_hi = outer["diel_amplitude"]["bounds"]
    phase_lo, phase_hi = outer["diel_phase_hours"]["bounds"]
    x0 = np.array([outer["diel_amplitude"]["initial"], outer["diel_phase_hours"]["initial"]])

    history: list[dict[str, Any]] = []

    def objective(x: np.ndarray) -> float:
        amp = float(np.clip(x[0], amp_lo, amp_hi))
        phase = float(np.clip(x[1], phase_lo, phase_hi))
        # Penalise softly outside bounds so Nelder-Mead's reflections stay sensible
        out_of_bounds_penalty = 0.0
        if x[0] != amp or x[1] != phase:
            out_of_bounds_penalty = 10.0 * ((x[0] - amp) ** 2 + (x[1] - phase) ** 2)

        d = diel_multiplier(timestamps, amp, phase)
        _, pred, _ = solve_bounded(
            a_full,
            obs,
            sources,
            prior_lambda=config["calibration"]["prior_lambda"],
            smoothness_lambda=config["calibration"]["smoothness_lambda"],
            diel=d,
        )
        loss = weighted_log_mse(pred, obs) + out_of_bounds_penalty
        history.append({"amp": amp, "phase": phase, "loss": loss})
        return loss

    log.info("v3 outer optimization (Nelder-Mead) starting from amp=%.2f phase=%.2f", x0[0], x0[1])
    res = minimize(
        objective,
        x0,
        method=outer["method"],
        options={
            "maxiter": outer["maxiter"],
            "xatol": outer["xatol"],
            "fatol": outer["fatol"],
            "disp": False,
        },
    )
    amp_star = float(np.clip(res.x[0], amp_lo, amp_hi))
    phase_star = float(np.clip(res.x[1], phase_lo, phase_hi))
    log.info(
        "v3 fit done: amp=%.3f phase=%.3f h, loss=%.4f, n_eval=%d",
        amp_star,
        phase_star,
        float(res.fun),
        int(res.nfev),
    )

    d = diel_multiplier(timestamps, amp_star, phase_star)
    rates, pred, rms = solve_bounded(
        a_full,
        obs,
        sources,
        prior_lambda=config["calibration"]["prior_lambda"],
        smoothness_lambda=config["calibration"]["smoothness_lambda"],
        diel=d,
    )
    return {
        "diel_amplitude": amp_star,
        "diel_phase_hours": phase_star,
        "rates": rates,
        "pred_train": pred,
        "rms_train": rms,
        "n_outer_eval": int(res.nfev),
        "outer_loss": float(res.fun),
        "history": history,
    }


# ---------- metrics ---------- #


def per_receptor_metrics(
    pred: np.ndarray, obs: np.ndarray, receptor_names: list[str]
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r_idx, rname in enumerate(receptor_names):
        valid = ~np.isnan(obs[:, r_idx])
        if valid.sum() < 5:
            out[rname] = {
                "r": float("nan"),
                "rms": float("nan"),
                "peak_ratio": float("nan"),
                "n": int(valid.sum()),
            }
            continue
        p = pred[valid, r_idx]
        o = obs[valid, r_idx]
        corr = float(np.corrcoef(p, o)[0, 1])
        rms = float(np.sqrt(np.mean((p - o) ** 2)))
        peak_ratio = float(np.max(p) / np.max(o)) if np.max(o) > 0 else float("nan")
        out[rname] = {"r": corr, "rms": rms, "peak_ratio": peak_ratio, "n": int(valid.sum())}
    return out


def predict_on_window(
    rates: np.ndarray,
    a_full: np.ndarray,
    timestamps: list[str],
    diel_amp: float | None,
    diel_phase: float | None,
) -> np.ndarray:
    """Re-apply diel modulation (if given) and propagate fitted baselines."""
    if diel_amp is None or diel_phase is None:
        return a_full @ rates
    d = diel_multiplier(timestamps, diel_amp, diel_phase)
    return d[:, None] * (a_full @ rates)


# ---------- main ---------- #


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Mar 13-15 smoke test only")
    args = parser.parse_args()

    OUTPUTS.mkdir(exist_ok=True)
    config = load_config()
    parquet_path = HERE / config["data"]["modeldata_h2s_nofill"]

    if args.quick:
        log.info("quick mode: Mar 13-15 only; no holdout")
        train_w = config["windows"]["quick"]
        holdout_w = None
    else:
        train_w = config["windows"]["train"]
        holdout_w = config["windows"]["holdout"]

    log.info("loading train window %s -> %s", train_w["start"], train_w["end"])
    df_train = load_window(parquet_path, train_w["start"], train_w["end"])
    receptor_names = config["receptors"]
    met_train, obs_train, hours_train = build_met_and_obs(df_train, receptor_names)
    log.info(
        "train: %d hours, %d/%d obs non-NaN",
        len(met_train),
        int((~np.isnan(obs_train)).sum()),
        obs_train.size,
    )

    sources = build_source_field(config)
    log.info("source field: %d sources", len(sources))

    receptors_core = [
        Receptor(name=n, lat=lat, lon=lon, height_m=2.0)
        for n, (lat, lon) in ((rn, RECEPTOR_COORDS[rn]) for rn in receptor_names)
    ]

    log.info("precomputing unit-rate footprint A_full on train window…")
    unit_sources = [
        Source(
            name=s.name,
            lat=s.lat,
            lon=s.lon,
            emission_rate_g_s=1.0,
            height_m=s.height_m,
            archetype=s.archetype,
        )
        for s in sources
    ]
    a_train = forward_run_per_source(unit_sources, receptors_core, met_train, units="ppb")
    log.info("A_train shape: %s", a_train.shape)

    # ---------- v2 baseline (no diel) ---------- #
    log.info("v2 baseline (no diel): bounded NNLS on train…")
    rates_v2, pred_train_v2, rms_train_v2 = solve_bounded(
        a_train,
        obs_train,
        sources,
        prior_lambda=config["calibration"]["prior_lambda"],
        smoothness_lambda=config["calibration"]["smoothness_lambda"],
        diel=None,
    )
    metrics_train_v2 = per_receptor_metrics(pred_train_v2, obs_train, receptor_names)
    log.info("v2 train metrics: %s", {r: round(m["r"], 3) for r, m in metrics_train_v2.items()})

    # ---------- v3 (diel modifier) ---------- #
    log.info("v3 (diel modifier): outer Nelder-Mead over (amplitude, phase)…")
    timestamps_train = [m.timestamp for m in met_train]
    v3_out = fit_v3(a_train, obs_train, timestamps_train, sources, config)
    metrics_train_v3 = per_receptor_metrics(v3_out["pred_train"], obs_train, receptor_names)
    log.info("v3 train metrics: %s", {r: round(m["r"], 3) for r, m in metrics_train_v3.items()})

    # ---------- holdout evaluation ---------- #
    metrics_holdout_v2: dict[str, dict[str, float]] = {}
    metrics_holdout_v3: dict[str, dict[str, float]] = {}
    wind_v2_holdout: pd.DataFrame | None = None
    wind_v3_holdout: pd.DataFrame | None = None
    pred_holdout_v2 = pred_holdout_v3 = None
    obs_holdout = None
    met_holdout: list[MetCondition] = []
    hours_holdout: pd.DatetimeIndex | None = None

    if holdout_w is not None:
        log.info("loading holdout window %s -> %s", holdout_w["start"], holdout_w["end"])
        df_holdout = load_window(parquet_path, holdout_w["start"], holdout_w["end"])
        met_holdout, obs_holdout, hours_holdout = build_met_and_obs(df_holdout, receptor_names)
        log.info(
            "holdout: %d hours, %d/%d obs non-NaN",
            len(met_holdout),
            int((~np.isnan(obs_holdout)).sum()),
            obs_holdout.size,
        )

        log.info("precomputing A_full on holdout window…")
        a_holdout = forward_run_per_source(unit_sources, receptors_core, met_holdout, units="ppb")

        pred_holdout_v2 = predict_on_window(
            rates_v2, a_holdout, [m.timestamp for m in met_holdout], None, None
        )
        pred_holdout_v3 = predict_on_window(
            v3_out["rates"],
            a_holdout,
            [m.timestamp for m in met_holdout],
            v3_out["diel_amplitude"],
            v3_out["diel_phase_hours"],
        )
        metrics_holdout_v2 = per_receptor_metrics(pred_holdout_v2, obs_holdout, receptor_names)
        metrics_holdout_v3 = per_receptor_metrics(pred_holdout_v3, obs_holdout, receptor_names)
        log.info(
            "v2 holdout metrics: %s", {r: round(m["r"], 3) for r, m in metrics_holdout_v2.items()}
        )
        log.info(
            "v3 holdout metrics: %s", {r: round(m["r"], 3) for r, m in metrics_holdout_v3.items()}
        )

        wind_v2_holdout = wind_conditional_residuals(
            pred_holdout_v2, obs_holdout, met_holdout, receptor_names
        )
        wind_v3_holdout = wind_conditional_residuals(
            pred_holdout_v3, obs_holdout, met_holdout, receptor_names
        )

    # ---------- write artifacts ---------- #
    log.info("writing artifacts to %s", OUTPUTS)

    pd.DataFrame(
        {
            "name": [s.name for s in sources],
            "archetype": [s.archetype for s in sources],
            "rate_g_s": rates_v2,
        }
    ).to_csv(OUTPUTS / "fitted_rates_v2.csv", index=False)

    pd.DataFrame(
        {
            "name": [s.name for s in sources],
            "archetype": [s.archetype for s in sources],
            "rate_g_s": v3_out["rates"],
        }
    ).to_csv(OUTPUTS / "fitted_rates_v3.csv", index=False)

    def ts_df(
        hours: pd.DatetimeIndex,
        obs_arr: np.ndarray,
        pred_v2_arr: np.ndarray,
        pred_v3_arr: np.ndarray,
    ) -> pd.DataFrame:
        cols: dict[str, np.ndarray] = {"hour": hours.astype(str)}
        for i, r in enumerate(receptor_names):
            cols[f"obs_{r}"] = obs_arr[:, i]
            cols[f"pred_v2_{r}"] = pred_v2_arr[:, i]
            cols[f"pred_v3_{r}"] = pred_v3_arr[:, i]
        return pd.DataFrame(cols)

    pred_train_v3 = v3_out["pred_train"]
    ts_df(hours_train, obs_train, pred_train_v2, pred_train_v3).to_csv(
        OUTPUTS / "timeseries_train.csv", index=False
    )
    if (
        holdout_w is not None
        and hours_holdout is not None
        and obs_holdout is not None
        and pred_holdout_v2 is not None
        and pred_holdout_v3 is not None
    ):
        ts_df(hours_holdout, obs_holdout, pred_holdout_v2, pred_holdout_v3).to_csv(
            OUTPUTS / "timeseries_holdout.csv", index=False
        )
    if wind_v2_holdout is not None:
        wind_v2_holdout.to_csv(OUTPUTS / "wind_residuals_v2.csv", index=False)
    if wind_v3_holdout is not None:
        wind_v3_holdout.to_csv(OUTPUTS / "wind_residuals_v3.csv", index=False)

    # ---------- W/SW residual at SAN YSIDRO (the acceptance-criteria diagnostic) ---------- #
    def san_ysidro_wsw_resid(wind_df: pd.DataFrame | None) -> float | None:
        if wind_df is None:
            return None
        sub = wind_df[
            (wind_df["receptor"] == "SAN YSIDRO") & wind_df["wind_sector"].isin(["W", "SW", "WSW"])
        ]
        if sub.empty:
            return None
        return float((sub["resid_mean"] * sub["n_hours"]).sum() / sub["n_hours"].sum())

    wsw_v2 = san_ysidro_wsw_resid(wind_v2_holdout)
    wsw_v3 = san_ysidro_wsw_resid(wind_v3_holdout)

    summary: dict[str, Any] = {
        "experiment": "calibration_v3",
        "run_date": pd.Timestamp.now().isoformat(),
        "quick_mode": args.quick,
        "windows": {"train": train_w, "holdout": holdout_w},
        "n_sources": len(sources),
        "n_obs_train": int((~np.isnan(obs_train)).sum()),
        "n_obs_holdout": int((~np.isnan(obs_holdout)).sum()) if obs_holdout is not None else 0,
        "v2": {
            "rms_train": rms_train_v2,
            "train_metrics": metrics_train_v2,
            "holdout_metrics": metrics_holdout_v2,
            "san_ysidro_wsw_residual_holdout": wsw_v2,
        },
        "v3": {
            "diel_amplitude": v3_out["diel_amplitude"],
            "diel_phase_hours": v3_out["diel_phase_hours"],
            "rms_train": float(np.sqrt(np.nanmean((v3_out["pred_train"] - obs_train) ** 2))),
            "train_metrics": metrics_train_v3,
            "holdout_metrics": metrics_holdout_v3,
            "san_ysidro_wsw_residual_holdout": wsw_v3,
            "n_outer_eval": v3_out["n_outer_eval"],
            "outer_loss": v3_out["outer_loss"],
        },
        "acceptance": {
            "san_ysidro_holdout_r_improved": (
                (metrics_holdout_v3.get("SAN YSIDRO", {}).get("r") or 0.0)
                > (metrics_holdout_v2.get("SAN YSIDRO", {}).get("r") or 0.0)
            )
            if not args.quick
            else None,
            "wsw_residual_reduction_pct": (
                float(100.0 * (1.0 - abs(wsw_v3) / abs(wsw_v2)))
                if (wsw_v2 is not None and wsw_v3 is not None and abs(wsw_v2) > 1e-6)
                else None
            ),
            "nestor_holdout_r_regression": (
                (metrics_holdout_v3.get("NESTOR - BES", {}).get("r") or 0.0)
                - (metrics_holdout_v2.get("NESTOR - BES", {}).get("r") or 0.0)
            )
            if not args.quick
            else None,
        },
    }
    (OUTPUTS / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("done; summary.json + timeseries_*.csv + wind_residuals_*.csv in %s", OUTPUTS)


if __name__ == "__main__":
    main()
