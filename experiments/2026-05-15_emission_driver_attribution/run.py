"""
Emission-driver attribution for Berry's calm-night extremes.

Why
---
`2026-05-15_box_calibration` proved the shipped stagnation box is
*necessary but not sufficient*: with a **constant** lumped emission its
held-out rank-skill ceiling on Berry (NESTOR - BES) stagnation hours is
only Spearman ≈ 0.13 (operational `is_stagnation`) / 0.22
(`stable_atm`) — amplitude-invariant, so no calibration of E_local can
beat it. The residual variance is *emission-driven*. The proposed next
component is a time-varying `E_local(t)`.

Before designing that, this experiment answers the design-critical
question with data, not a guess: **which exogenous drivers carry
Berry's calm-night extreme variance, and does driving the box with
them clear the constant-box rank-skill ceiling?**

What is tested (held-out, chronological 70/30 — same split as the
calibration experiment, so numbers are directly comparable):

  1. Per-driver Spearman vs Berry stagnation-hour H2S, split into
     EXOGENOUS (usable in a forward emissions model) and
     AUTOREGRESSIVE (h2s_lag/rolling — *not* usable as an exogenous
     driver; reported only to bound how predictable these hours are
     at all, clearly flagged).
  2. The **existing service `emissions.py` form**, UNFITTED (literature
     default `EmissionParameters`): m(t) = f_temperature · f_substrate
     · f_volatilization('drain') · f_diel. Does the parametric form we
     already ship carry calm-night rank signal out of the box?
  3. A fitted **upper bound**: non-negative least squares of the
     standardized top exogenous drivers (fit on train, Spearman on
     test). Bounds the best an emission-driver term could deliver
     with the inputs available in `modeldata_h2s_nofill`.

The bar for every number is the constant-box ceiling: **0.127**
(operational) / **0.218** (`stable_atm`). A driver term is only worth
adding to the service if it clears that on held-out data.

Reproduce
---------
    uv pip install -e ../tijuana-dispersion   # box+emissions on main
    uv run python experiments/2026-05-15_emission_driver_attribution/run.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls
from scipy.stats import spearmanr
from tijuana_dispersion import MetCondition
from tijuana_dispersion.emissions import (
    EmissionDrivers,
    EmissionParameters,
    f_diel,
    f_substrate,
    f_temperature,
    f_volatilization,
)
from tijuana_dispersion.regime import is_stagnation

HERE = Path(__file__).parent
OUT = HERE / "output"
PARQUET = HERE / "../../data/modeldata_h2s_nofill.parquet"
BERRY = "NESTOR - BES"
TRAIN_FRAC = 0.70

# Ceiling to beat — from 2026-05-15_box_calibration (held-out).
BOX_CEILING = {"is_stagnation": 0.127, "stable_atm": 0.218}

EXOGENOUS = [
    "temperature_2m",
    "sbiwtp_flow_mgd",
    "sbiwtp_deficit",
    "sbiwtp_sli",
    "sbiwtp_anomaly",
    "sbiwtp_hourly_mgd",
    "sbiwtp_flow_x_temp",
    "flow_log",
    "flow_rolling_24h",
    "flow_lag_6h",
    "Flow (m^3/s)--Border",
    "tide_height",
    "precipitation",
    "wind_temp_interaction",
    "relative_humidity_2m",
    "surface_pressure",
]
AUTOREGRESSIVE = ["h2s_lag_1h", "h2s_lag_3h", "h2s_lag_6h", "h2s_rolling_6h", "h2s_rolling_24h"]


def _rho(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or np.allclose(b, b[0]) or np.allclose(a, a[0]):
        return float("nan")
    return float(spearmanr(a, b).statistic)


def _emissions_form_unfitted(berry: pd.DataFrame) -> np.ndarray:
    """The shipped emissions.py multiplicative modifier with literature
    default parameters — no fitting. 'drain' archetype (Berry's
    dominant nearby source class)."""
    p = EmissionParameters()
    out = np.zeros(len(berry))
    for i, (_, row) in enumerate(berry.iterrows()):
        d = EmissionDrivers.from_dataframe_row(row)
        out[i] = (
            f_temperature(d.temperature_c, p)
            * f_substrate(d, p)
            * f_volatilization(d, p, "drain")
            * f_diel(d, p)
        )
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    df = pd.read_parquet(PARQUET)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    berry = (
        df[df.site_name == BERRY]
        .dropna(subset=["H2S", "wind_speed_10m", "temperature_2m", "is_night"])
        .sort_values("time")
        .reset_index(drop=True)
    )
    obs = berry["H2S"].to_numpy(dtype=float)

    met = [
        MetCondition(
            timestamp=t.isoformat(),
            wind_speed_ms=float(ws),
            wind_direction_deg=float(wd),
            temperature_c=float(tc),
            cloud_cover_frac=float(cc) / 100.0,
            is_night=bool(int(n)),
        )
        for t, ws, wd, tc, cc, n in zip(
            berry["time"],
            berry["wind_speed_10m"],
            berry["wind_direction_10m"].fillna(0.0),
            berry["temperature_2m"],
            berry["cloud_cover"].fillna(50.0),
            berry["is_night"],
            strict=True,
        )
    ]
    regimes = {
        "is_stagnation": np.array([is_stagnation(m) for m in met]),
        "stable_atm": berry["stable_atm"].astype(str).isin(["1", "True"]).to_numpy(),
    }

    n = len(berry)
    is_train = np.zeros(n, dtype=bool)
    is_train[: int(n * TRAIN_FRAC)] = True

    emis_unfitted = _emissions_form_unfitted(berry)

    report: dict[str, object] = {
        "n_berry_hours": int(n),
        "n_berry_gt100": int((obs > 100).sum()),
        "box_ceiling_to_beat_heldout_spearman": BOX_CEILING,
        "split": "chronological 70/30 (matches box_calibration)",
    }

    for rname, rmask in regimes.items():
        test_m = rmask & ~is_train
        train_m = rmask & is_train
        ot = obs[test_m]

        # 1. per-driver Spearman on held-out regime hours
        def driver_rhos(
            cols: list[str], tm: np.ndarray = test_m, o: np.ndarray = ot
        ) -> dict[str, float]:
            r = {}
            for c in cols:
                if c not in berry.columns:
                    continue
                v = berry[c].to_numpy(dtype=float)[tm]
                if np.isnan(v).any():
                    v = np.nan_to_num(v, nan=float(np.nanmedian(v)))
                r[c] = round(_rho(o, v), 4)
            return dict(sorted(r.items(), key=lambda kv: -abs(kv[1])))

        exo = driver_rhos(EXOGENOUS)
        auto = driver_rhos(AUTOREGRESSIVE)

        # 2. shipped emissions.py form, unfitted
        rho_emis = round(_rho(ot, emis_unfitted[test_m]), 4)

        # 3. fitted upper bound: NNLS of standardized top-6 exogenous
        #    drivers (fit on train regime, evaluate rank on test).
        top = [c for c in list(exo)[:6] if c in berry.columns]
        X = berry[top].to_numpy(dtype=float)
        X = np.nan_to_num(X, nan=np.nanmedian(X))
        mu, sd = X[train_m].mean(0), X[train_m].std(0) + 1e-9
        Xs = (X - mu) / sd
        coef, _ = nnls(Xs[train_m], obs[train_m])
        pred_test = Xs[test_m] @ coef
        rho_fit = round(_rho(ot, pred_test), 4)

        ceiling = BOX_CEILING[rname]
        report[rname] = {
            "n_test_regime_hours": int(test_m.sum()),
            "n_train_regime_hours": int(train_m.sum()),
            "exogenous_driver_spearman_heldout": exo,
            "autoregressive_REFERENCE_ONLY_not_a_driver": auto,
            "shipped_emissions_form_unfitted_spearman": rho_emis,
            "fitted_top6_exogenous_upperbound_spearman": rho_fit,
            "fitted_upperbound_drivers": top,
            "beats_constant_box_ceiling": {
                "ceiling": ceiling,
                "best_single_exogenous": (max(exo.values(), key=abs) if exo else float("nan")),
                "emissions_form_unfitted_beats": bool(abs(rho_emis) > ceiling),
                "fitted_upperbound_beats": bool(abs(rho_fit) > ceiling),
            },
        }

    verdict_lines = []
    for rname in regimes:
        rr = report[rname]
        assert isinstance(rr, dict)
        bb = rr["beats_constant_box_ceiling"]
        verdict_lines.append(
            f"[{rname}] ceiling={bb['ceiling']:.3f} | "
            f"best single exo={bb['best_single_exogenous']:.3f} | "
            f"emissions-form(unfitted)={rr['shipped_emissions_form_unfitted_spearman']:.3f} | "
            f"fitted upper bound={rr['fitted_top6_exogenous_upperbound_spearman']:.3f} | "
            f"upper-bound clears ceiling: {bb['fitted_upperbound_beats']}"
        )
    report["verdict"] = verdict_lines

    (OUT / "summary.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
