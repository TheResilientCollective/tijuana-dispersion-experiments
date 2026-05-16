"""
Event-trigger magnitude: can an episodic trigger recover recall@100?

Arc
---
`box_driver_calibration` (2026-05-16) validated the box→temperature
driver as a calm-night *ranker* (held-out Spearman ~0.27/0.34, ~2× the
constant box) but it is **not** a magnitude predictor: recall@100 =
0.00, extremes under-predicted ~17–20×. A single fitted amplitude
cannot span the 1→750 ppb range. The open lever (explicitly *not*
more emission-driver tuning): an **episodic trigger** that boosts the
box's local emission on event hours.

This experiment tests exactly that, through the **shipped #6
interface**: `temperature_led_e_local(..., substrate=trigger)` — the
optional element-wise multiplier the #6 design left as a hook. So a
positive result is directly actionable (it *is* the substrate hook);
a negative result closes the magnitude line for this data.

    E_local(t) = E0 · Q10^((T−T_ref)/10) · [1 + (B−1)·1{trig(t) ≥ θ}]

Honesty controls
----------------
- Same Berry, same chronological 70/30 split as the three prior
  experiments → numbers compare directly. Baseline = the calibrated
  driver box (rank-optimal Q10=5, τ=12) → recall@100 = 0.
- recall@100 alone is gameable (boost everything → recall 1,
  precision 0). The train objective is **Youden's J = recall − FPR**
  at 100 ppb (balanced, not gamed by blanket boosting); held-out
  recall, precision, FPR, F1 and Spearman are all reported.
- **EXOGENOUS triggers** (flow/SBIWTP/precip — forward-usable) are
  separated from the **AUTOREGRESSIVE reference** (`h2s_lag_1h`: uses
  observed H2S, *not* forward-usable — reported only to bound the
  achievable recall ceiling, clearly flagged).
- θ is a TRAIN percentile; B from a fixed grid; E0 closed-form (box
  linear in E0) re-fit per trigger config on TRAIN. No metric on
  fitted data.

Reproduce
---------
    uv run python experiments/2026-05-16_event_trigger_magnitude/run.py
(service pinned v0.4.0.)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from tijuana_dispersion import MetCondition
from tijuana_dispersion.regime import is_stagnation
from tijuana_dispersion.stagnation import (
    StagnationBoxParams,
    TemperatureEmissionParams,
    box_series,
    temperature_led_e_local,
)

HERE = Path(__file__).parent
OUT = HERE / "output"
PARQUET = HERE / "../../data/modeldata_h2s_nofill.parquet"
BERRY = "NESTOR - BES"
TRAIN_FRAC = 0.70
THR = 100.0

# Calibrated driver (rank-optimal, from box_driver_calibration).
Q10, TAU_H, T_REF_C = 5.0, 12.0, 20.0
DEFAULT_AREA_M2 = StagnationBoxParams().area_m2

# Forward-usable episodic features (oriented so high = potential event).
EXO_TRIGGERS = [
    "sbiwtp_anomaly",
    "sbiwtp_deficit",
    "sbiwtp_flow_x_temp",
    "flow_log",
    "flow_rolling_24h",
    "Flow (m^3/s)--Border",
    "precipitation",
]
# Reference only — autoregressive, NOT forward-usable. Bounds the ceiling.
AUTO_TRIGGER = "h2s_lag_1h"
PCTL_GRID = [85.0, 90.0, 95.0, 98.0]
BOOST_GRID = [3.0, 10.0, 30.0, 100.0, 300.0]


def _clf(o: np.ndarray, p: np.ndarray) -> dict[str, float]:
    """recall / precision / FPR / F1 / Youden-J at the 100 ppb line."""
    hi_o, hi_p = o > THR, p > THR
    tp = int((hi_o & hi_p).sum())
    fp = int((~hi_o & hi_p).sum())
    fn = int((hi_o & ~hi_p).sum())
    tn = int((~hi_o & ~hi_p).sum())
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "recall_at_100": round(rec, 3),
        "precision_at_100": round(prec, 3),
        "fpr_at_100": round(fpr, 3),
        "f1_at_100": round(f1, 3),
        "youden_j": round(rec - fpr, 3),
    }


def _rho(o: np.ndarray, p: np.ndarray) -> float:
    if len(o) < 3 or np.allclose(p, p[0]):
        return float("nan")
    return round(float(spearmanr(o, p).statistic), 4)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    df = pd.read_parquet(PARQUET)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    berry = (
        df[df.site_name == BERRY]
        .dropna(
            subset=[
                "H2S",
                "wind_speed_10m",
                "wind_direction_10m",
                "temperature_2m",
                "cloud_cover",
                "is_night",
            ]
        )
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
            is_night=bool(int(nn)),
        )
        for t, ws, wd, tc, cc, nn in zip(
            berry["time"],
            berry["wind_speed_10m"],
            berry["wind_direction_10m"],
            berry["temperature_2m"],
            berry["cloud_cover"],
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

    # Unit temperature-led E_local (E0=1); box is linear in E0.
    e_temp_unit = temperature_led_e_local(
        met, TemperatureEmissionParams(e0_g_s=1.0, q10=Q10, t_ref_c=T_REF_C)
    )

    def box_for(trigger_mult: np.ndarray) -> np.ndarray:
        return box_series(
            met,
            StagnationBoxParams(
                tau_h=TAU_H, e_local_g_s=e_temp_unit * trigger_mult, area_m2=DEFAULT_AREA_M2
            ),
            units="ppb",
        )

    def fit_e0(pu: np.ndarray, m: np.ndarray) -> float:
        pt = pu[m]
        d = float(np.dot(pt, pt))
        return max(0.0, float(np.dot(obs[m], pt) / d)) if d > 0 else 0.0

    report: dict[str, object] = {
        "n_berry_hours": int(n),
        "n_berry_gt100": int((obs > THR).sum()),
        "calibrated_driver": {"q10": Q10, "tau_h": TAU_H, "t_ref_c": T_REF_C},
        "split": "chronological 70/30 (matches prior experiments)",
        "baseline_note": "driver box (no trigger) recall@100 = 0.00 (box_driver_calibration)",
    }

    for rname, rmask in regimes.items():
        tr, te = rmask & is_train, rmask & ~is_train

        # No-trigger baseline (re-derived here for an apples comparison).
        pu0 = box_for(np.ones(n))
        base_pred = fit_e0(pu0, tr) * pu0
        base = {**_clf(obs[te], base_pred[te]), "spearman": _rho(obs[te], base_pred[te])}

        def best_over(
            features: list[str], tr: np.ndarray = tr, te: np.ndarray = te
        ) -> dict[str, object]:
            best: dict[str, object] | None = None
            best_j_tr = -2.0
            for feat in features:
                if feat not in berry.columns:
                    continue
                fv = berry[feat].to_numpy(dtype=float)
                fv = np.nan_to_num(fv, nan=float(np.nanmedian(fv)))
                for pct in PCTL_GRID:
                    thr_v = float(np.percentile(fv[tr], pct)) if tr.any() else np.inf
                    fired = fv >= thr_v
                    for B in BOOST_GRID:
                        mult = np.where(fired, B, 1.0)
                        pu = box_for(mult)
                        pred = fit_e0(pu, tr) * pu
                        j_tr = _clf(obs[tr], pred[tr])["youden_j"]
                        if j_tr > best_j_tr:
                            best_j_tr = j_tr
                            best = {
                                "feature": feat,
                                "train_percentile": pct,
                                "boost": B,
                                "train_youden_j": j_tr,
                                "test": {
                                    **_clf(obs[te], pred[te]),
                                    "spearman": _rho(obs[te], pred[te]),
                                },
                            }
            return best or {"error": "no usable feature"}

        exo = best_over(EXO_TRIGGERS)
        auto = best_over([AUTO_TRIGGER])

        report[rname] = {
            "n_test_regime_hours": int(te.sum()),
            "n_test_gt100": int((obs[te] > THR).sum()),
            "no_trigger_baseline_test": base,
            "best_EXOGENOUS_trigger_forward_usable": exo,
            "best_AUTOREGRESSIVE_trigger_REFERENCE_ONLY": auto,
        }

    verdict = []
    for rn in regimes:
        rr = report[rn]
        assert isinstance(rr, dict)
        ex = rr["best_EXOGENOUS_trigger_forward_usable"]
        au = rr["best_AUTOREGRESSIVE_trigger_REFERENCE_ONLY"]
        b = rr["no_trigger_baseline_test"]
        verdict.append(
            f"[{rn}] baseline recall@100={b['recall_at_100']:.2f} | "
            f"best EXOGENOUS recall={ex.get('test', {}).get('recall_at_100')}, "
            f"prec={ex.get('test', {}).get('precision_at_100')} "
            f"(feat={ex.get('feature')}) | AUTOREGRESSIVE ceiling "
            f"recall={au.get('test', {}).get('recall_at_100')}, "
            f"prec={au.get('test', {}).get('precision_at_100')}"
        )
    report["verdict"] = verdict

    (OUT / "summary.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
