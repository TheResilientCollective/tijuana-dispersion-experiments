"""
calibration v3.6 — nocturnal mixing-lid (limited-mixing Gaussian).

Tier-1 of the mixing-height design. A reflecting lid at height L(t)
traps emissions in a shallow stable boundary layer on calm clear
nights. Standard limited-mixing treatment: ground concentration cannot
fall below the fully-mixed value, so the effective vertical factor is

    V_lim = max( V_unbounded ,  sqrt(2*pi) * sigma_z / L )

Expressed as a multiplicative factor on the *unbounded* footprint:

    factor[t,r,s] = max( 1 ,  sqrt(2*pi) * sigma_z[t,r,s]
                                 / ( L[t] * V_unbounded[t,r,s] ) )   >= 1

so it stays LINEAR in emission rate and slots into the existing
bounded-NNLS machinery (same trick as the diel multiplier).

L(t) = clip( k_L * max(u,0.5) * s(stability), L_min, L_max )
       s = {A:2.5,B:2.0,C:1.5,D:1.0,E:0.5,F:0.3}
k_L is fitted in the outer loop alongside single-amp diel (amp,phase).

Compares BASELINE (no lid = v3.5 single-amp diel) vs v3.6 (lid) on the
Apr holdout, with Spearman as headline (per the metric reframe) plus a
calm-night-extreme submetric — the regime the lid targets.

Reuses v3.5's data/source/NNLS code by import (DRY).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr
from tijuana_dispersion.core import (
    R_EARTH,
    Source,
    briggs_sigma,
    pasquill_stability,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HERE = Path(__file__).parent
OUTPUTS = HERE / "output"

# --- import v3.5's run.py as a module (DRY: reuse its data/source/NNLS code) ---
_V35 = HERE / "../2026-05-12_calibration_v3_5_sy_nearfield/run.py"
_spec = importlib.util.spec_from_file_location("v35", _V35)
v35 = importlib.util.module_from_spec(_spec)
sys.modules["v35"] = v35
_spec.loader.exec_module(v35)


def load_config() -> dict[str, Any]:
    import yaml

    with (HERE / "config.yaml").open() as f:
        return yaml.safe_load(f)


def ugm3_to_ppb(ugm3: np.ndarray, temp_c: np.ndarray) -> np.ndarray:
    """Vectorised copy of core.ugm3_to_ppb_h2s (H2S, MW 34.08)."""
    vm = 24.45 * (273.15 + temp_c) / (273.15 + 25.0)
    return ugm3 * vm / 34.08


def precompute_geometry(
    sources: list[Source],
    receptor_coords: list[tuple[float, float, float]],  # (lat, lon, height_m)
    met: list,  # list[MetCondition]
) -> dict[str, np.ndarray]:
    """Per-(t,r,s): unbounded ppb footprint A0, sigma_z, V_unbounded;
    per-t: wind speed u, Pasquill class index. Mirrors core's
    gaussian_plume_concentration exactly so the lid ratio is consistent.
    """
    n_t, n_r, n_s = len(met), len(receptor_coords), len(sources)
    s_lat = np.array([s.lat for s in sources])
    s_lon = np.array([s.lon for s in sources])
    s_H = np.array([s.height_m for s in sources])
    r_lat = np.array([c[0] for c in receptor_coords])
    r_lon = np.array([c[1] for c in receptor_coords])
    r_z = np.array([c[2] for c in receptor_coords])

    # Local frame is per-source (core centres lat/lon on the source).
    # rx,ry[r,s] = receptor position in meters relative to source. t-independent.
    lat0 = s_lat[None, :]  # (1,s)
    rx = R_EARTH * np.radians(r_lon[:, None] - s_lon[None, :]) * np.cos(np.radians(lat0))
    ry = R_EARTH * (np.radians(r_lat[:, None]) - np.radians(s_lat[None, :]))  # (r,s)

    A0 = np.zeros((n_t, n_r, n_s))
    SZ = np.full((n_t, n_r, n_s), np.nan)
    VUNB = np.ones((n_t, n_r, n_s))
    u_arr = np.empty(n_t)
    stab_idx = np.empty(n_t, dtype=int)
    STAB = "ABCDEF"

    for ti, m in enumerate(met):
        u = max(m.wind_speed_ms, 0.5)
        u_arr[ti] = u
        stab = pasquill_stability(u, m.is_night, m.cloud_cover_frac)
        stab_idx[ti] = STAB.index(stab)
        phi = math.radians((m.wind_direction_deg + 180.0) % 360.0)
        sin_p, cos_p = math.sin(phi), math.cos(phi)
        X = rx * sin_p + ry * cos_p  # (r,s) downwind
        Y = rx * cos_p - ry * sin_p  # (r,s) crosswind
        downwind = X > 0.0
        sy, sz = briggs_sigma(stab, np.maximum(X, 1.0))  # (r,s)
        with np.errstate(over="ignore", invalid="ignore"):
            pref = 1e6 / (2.0 * math.pi * u * sy * sz)
            cross = np.exp(-0.5 * (Y / sy) ** 2)
            vert = np.exp(-0.5 * ((r_z[:, None] - s_H[None, :]) / sz) ** 2) + np.exp(
                -0.5 * ((r_z[:, None] + s_H[None, :]) / sz) ** 2
            )
        ugm3 = np.where(downwind, pref * cross * vert, 0.0)
        ppb = ugm3_to_ppb(ugm3, np.full_like(ugm3, m.temperature_c))
        A0[ti] = np.where(downwind, ppb, 0.0)
        SZ[ti] = sz
        VUNB[ti] = np.where(vert > 1e-12, vert, 1e-12)

    return {"A0": A0, "sigma_z": SZ, "V_unbounded": VUNB, "u": u_arr, "stab_idx": stab_idx}


def lid_factor(geom: dict[str, np.ndarray], k_L: float, cfg_mix: dict[str, Any]) -> np.ndarray:
    """(n_t,n_r,n_s) multiplicative factor >= 1. L(t) per-timestep."""
    STAB = "ABCDEF"
    s_scale = np.array([cfg_mix["stability_scale"][c] for c in STAB])
    s_t = s_scale[geom["stab_idx"]]  # (n_t,)
    L = np.clip(k_L * geom["u"] * s_t, cfg_mix["L_min_m"], cfg_mix["L_max_m"])  # (n_t,)
    sz = geom["sigma_z"]
    vunb = geom["V_unbounded"]
    wellmixed_V = math.sqrt(2.0 * math.pi) * sz / L[:, None, None]
    return np.maximum(1.0, wellmixed_V / vunb)


def metrics(pred: np.ndarray, obs: np.ndarray) -> dict[str, float]:
    m = ~np.isnan(obs) & ~np.isnan(pred)
    o, p = obs[m], pred[m]
    if len(o) < 5 or np.std(p) == 0 or np.std(o) == 0:
        return {
            "spearman": float("nan"),
            "log_pearson": float("nan"),
            "pearson": float("nan"),
            "n": len(o),
        }
    return {
        "spearman": float(spearmanr(o, p).correlation),
        "log_pearson": float(np.corrcoef(np.log1p(o), np.log1p(np.clip(p, 0, None)))[0, 1]),
        "pearson": float(np.corrcoef(o, p)[0, 1]),
        "n": len(o),
    }


def fit(
    geom: dict[str, np.ndarray],
    obs: np.ndarray,
    timestamps: list[str],
    sources: list,
    config: dict[str, Any],
    with_lid: bool,
) -> dict[str, Any]:
    o = config["calibration"]["outer"]
    pl = config["calibration"]["prior_lambda"]
    sl = config["calibration"]["smoothness_lambda"]
    ab = config.get("archetype_overrides", {}).get("bounds", {})
    ap = config.get("archetype_overrides", {}).get("priors", {})
    cfg_mix = config["calibration"]["mixing"]
    amp_lo, amp_hi = o["diel_amplitude_land"]["bounds"]
    ph_lo, ph_hi = o["diel_phase_hours"]["bounds"]
    kL_lo, kL_hi = o["mixing_k_L"]["bounds"]
    x0 = (
        [
            o["diel_amplitude_land"]["initial"],
            o["diel_phase_hours"]["initial"],
            o["mixing_k_L"]["initial"],
        ]
        if with_lid
        else [o["diel_amplitude_land"]["initial"], o["diel_phase_hours"]["initial"]]
    )

    def unpack(x: np.ndarray) -> tuple[float, float, float, float]:
        amp = float(np.clip(x[0], amp_lo, amp_hi))
        ph = float(np.clip(x[1], ph_lo, ph_hi))
        kL = float(np.clip(x[2], kL_lo, kL_hi)) if with_lid else float("inf")
        pen = 10.0 * ((x[0] - amp) ** 2 + (x[1] - ph) ** 2)
        if with_lid:
            pen += 10.0 * (x[2] - kL) ** 2
        return amp, ph, kL, pen

    def build_A(kL: float) -> np.ndarray:
        if not with_lid:
            return geom["A0"]
        return geom["A0"] * lid_factor(geom, kL, cfg_mix)

    def objective(x: np.ndarray) -> float:
        amp, ph, kL, pen = unpack(x)
        diel = v35.diel_multiplier_global(timestamps, amp, ph)
        _, pred, _ = v35.solve_bounded(
            build_A(kL),
            obs,
            sources,
            prior_lambda=pl,
            smoothness_lambda=sl,
            diel=diel,
            arch_bounds=ab,
            arch_priors=ap,
        )
        return v35.weighted_log_mse(pred, obs) + pen

    res = minimize(
        objective,
        np.array(x0),
        method=o["method"],
        options={"maxiter": o["maxiter"], "xatol": o["xatol"], "fatol": o["fatol"], "disp": False},
    )
    amp, ph, kL, _ = unpack(res.x)
    diel = v35.diel_multiplier_global(timestamps, amp, ph)
    rates, pred, rms = v35.solve_bounded(
        build_A(kL),
        obs,
        sources,
        prior_lambda=pl,
        smoothness_lambda=sl,
        diel=diel,
        arch_bounds=ab,
        arch_priors=ap,
    )
    log.info(
        "%s fit: amp=%.3f phase=%.3f%s loss=%.4f nfev=%d",
        "v3.6(lid)" if with_lid else "baseline(no-lid)",
        amp,
        ph,
        f" k_L={kL:.1f}" if with_lid else "",
        float(res.fun),
        int(res.nfev),
    )
    return {
        "amp": amp,
        "phase": ph,
        "k_L": (kL if with_lid else None),
        "rates": rates,
        "pred_train": pred,
        "rms_train": rms,
        "nfev": int(res.nfev),
        "loss": float(res.fun),
    }


def predict(
    geom: dict[str, np.ndarray],
    rates: np.ndarray,
    timestamps: list[str],
    amp: float,
    phase: float,
    k_L: float | None,
    cfg_mix: dict[str, Any],
) -> np.ndarray:
    A = geom["A0"] if k_L is None else geom["A0"] * lid_factor(geom, k_L, cfg_mix)
    diel = v35.diel_multiplier_global(timestamps, amp, phase)
    a_mod = diel[:, None, None] * A
    return (a_mod * rates[None, None, :]).sum(axis=2)


def main() -> None:
    OUTPUTS.mkdir(exist_ok=True)
    config = load_config()
    parquet = HERE / config["data"]["modeldata_h2s_nofill"]
    rec_names = config["receptors"]
    rc = v35.RECEPTOR_COORDS
    receptor_coords = [(rc[n][0], rc[n][1], 2.0) for n in rec_names]
    cfg_mix = config["calibration"]["mixing"]

    tr, ho = config["windows"]["train"], config["windows"]["holdout"]
    df_tr = v35.load_window(parquet, tr["start"], tr["end"])
    met_tr, obs_tr, hrs_tr = v35.build_met_and_obs(df_tr, rec_names)
    df_ho = v35.load_window(parquet, ho["start"], ho["end"])
    met_ho, obs_ho, hrs_ho = v35.build_met_and_obs(df_ho, rec_names)
    log.info("train %d h, holdout %d h", len(met_tr), len(met_ho))

    sources = v35.build_source_field(config)
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
    log.info("source field: %d sources; precomputing geometry…", len(sources))
    g_tr = precompute_geometry(unit_sources, receptor_coords, met_tr)
    g_ho = precompute_geometry(unit_sources, receptor_coords, met_ho)

    ts_tr = [m.timestamp for m in met_tr]
    ts_ho = [m.timestamp for m in met_ho]

    base = fit(g_tr, obs_tr, ts_tr, sources, config, with_lid=False)
    v36 = fit(g_tr, obs_tr, ts_tr, sources, config, with_lid=True)

    pred_b = predict(g_ho, base["rates"], ts_ho, base["amp"], base["phase"], None, cfg_mix)
    pred_6 = predict(g_ho, v36["rates"], ts_ho, v36["amp"], v36["phase"], v36["k_L"], cfg_mix)

    mb = {r: metrics(pred_b[:, i], obs_ho[:, i]) for i, r in enumerate(rec_names)}
    m6 = {r: metrics(pred_6[:, i], obs_ho[:, i]) for i, r in enumerate(rec_names)}

    # Calm-night-extreme submetric at Berry (NESTOR-BES): the regime the lid targets.
    berry = rec_names.index("NESTOR - BES")
    u_ho = g_ho["u"]
    is_night = np.array([m.is_night for m in met_ho])
    calm_ext = is_night & (u_ho < 3.5) & (obs_ho[:, berry] > 50)
    sub = {
        "n_calm_night_extreme_hours": int(calm_ext.sum()),
        "berry_obs_mean": float(np.nanmean(obs_ho[calm_ext, berry])) if calm_ext.any() else None,
        "berry_pred_mean_baseline": float(np.nanmean(pred_b[calm_ext, berry]))
        if calm_ext.any()
        else None,
        "berry_pred_mean_v36": float(np.nanmean(pred_6[calm_ext, berry]))
        if calm_ext.any()
        else None,
        "berry_pred_max_baseline": float(np.nanmax(pred_b[calm_ext, berry]))
        if calm_ext.any()
        else None,
        "berry_pred_max_v36": float(np.nanmax(pred_6[calm_ext, berry])) if calm_ext.any() else None,
    }

    log.info("baseline holdout Spearman: %s", {r: round(mb[r]["spearman"], 3) for r in rec_names})
    log.info("v3.6     holdout Spearman: %s", {r: round(m6[r]["spearman"], 3) for r in rec_names})
    log.info(
        "calm-night-extreme @Berry: obs~%.0f  base~%.1f  v3.6~%.1f (max base %.1f / v3.6 %.1f)",
        sub["berry_obs_mean"] or 0,
        sub["berry_pred_mean_baseline"] or 0,
        sub["berry_pred_mean_v36"] or 0,
        sub["berry_pred_max_baseline"] or 0,
        sub["berry_pred_max_v36"] or 0,
    )

    pd.DataFrame(
        {
            "name": [s.name for s in sources],
            "archetype": [s.archetype for s in sources],
            "rate_baseline": base["rates"],
            "rate_v36": v36["rates"],
        }
    ).to_csv(OUTPUTS / "fitted_rates.csv", index=False)
    cols: dict[str, Any] = {"hour": hrs_ho.astype(str)}
    for i, r in enumerate(rec_names):
        cols[f"obs_{r}"] = obs_ho[:, i]
        cols[f"pred_baseline_{r}"] = pred_b[:, i]
        cols[f"pred_v36_{r}"] = pred_6[:, i]
    pd.DataFrame(cols).to_csv(OUTPUTS / "timeseries_holdout.csv", index=False)

    summary = {
        "experiment": "calibration_v3_6_mixing_lid",
        "run_date": pd.Timestamp.now().isoformat(),
        "n_sources": len(sources),
        "baseline_no_lid": {
            "amp": base["amp"],
            "phase": base["phase"],
            "holdout": mb,
            "loss": base["loss"],
        },
        "v3_6_lid": {
            "amp": v36["amp"],
            "phase": v36["phase"],
            "k_L": v36["k_L"],
            "holdout": m6,
            "loss": v36["loss"],
        },
        "calm_night_extreme_berry": sub,
    }
    (OUTPUTS / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("done; artifacts in %s", OUTPUTS)


if __name__ == "__main__":
    main()
