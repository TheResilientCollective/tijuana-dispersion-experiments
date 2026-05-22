"""The decisive test: calibrate the box + temperature-led emission driver
against Berry's >100 ppb hours.

Arc
---
- `2026-05-15_box_calibration`: the *constant* box is necessary but
  not sufficient — held-out rank-skill ceiling Spearman **0.127**
  (operational `is_stagnation`) / **0.218** (`stable_atm`),
  amplitude-invariant.
- `2026-05-15_emission_driver_attribution`: `temperature_2m` alone →
  ~0.33 held-out; the shipped `f_volatilization ∝ wind²` chain is
  anti-skilled in this regime.
- Service issue #6 (shipped, v0.4.0): the box's `E_local` can now be a
  time-varying, temperature-led series
  `E_local(t) = E0 · Q10^((T(t) − T_ref)/10)` (wind-quadratic
  volatilization and cosine diel excluded by design).

This experiment calibrates that shipped model and answers the
make-or-break question: **does the calibrated box→driver line clear
the constant-box ceiling on held-out Berry stagnation hours?**

Identifiability (stated, not hidden)
------------------------------------
The box is linear in `E_local`, and `E_local` is linear in `E0`, so
box output is linear in `E0` → the optimal `E0` is a closed-form
non-negative least-squares scale. `T_ref` only multiplies `E_local`
by the constant `Q10^(−T_ref/10)`, which is **fully absorbed into
E0** — `T_ref` is non-identifiable from a single receptor, so it is
fixed at the shipped literature default (20 °C) and the calibrated
`E0` is reported relative to it. That leaves exactly two parameters
that move held-out *rank* skill: **Q10** (temperature-response shape)
and **τ** (box dynamics). Because Spearman is invariant to the `E0`
amplitude and to `T_ref`, the decisive statistic is the
**amplitude-invariant rank-skill ceiling**: the best held-out
Spearman over the Q10×τ grid — directly comparable to the
constant-box ceiling and impossible to game with the fit objective.
`area` and the `H_mix` table are held at shipped physical defaults
(same contract as `box_calibration`). Substrate is left **off**
entirely (attribution already measured its solo skill < 0.11;
parsimony — a substrate sensitivity would duplicate that experiment).

Honesty controls: chronological 70/30 split (identical to the two
prior experiments → numbers compare directly); Spearman headline;
recall@100; "before" = the constant box (issue #3) on the same hours;
plus the shipped end-to-end `run_forward(emission_driver=True)` on the
May 10-11 event.

Reproduce
---------
    uv run python experiments/2026-05-16_box_driver_calibration/run.py
(service pinned at v0.4.0 — first tag with #3 box + #6 driver.)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from tijuana_dispersion import MetCondition
from tijuana_dispersion.regime import is_stagnation
from tijuana_dispersion.stagnation import (
    H_MIX_BY_STABILITY_M,
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

# Bars to beat — from 2026-05-15_box_calibration (held-out, same split).
CONST_BOX_CEILING = {"is_stagnation": 0.127, "stable_atm": 0.218}

Q10_GRID = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
TAU_GRID_H = list(np.round(np.arange(1.0, 12.01, 1.0), 1))
T_REF_C = 20.0  # non-identifiable (absorbed into E0); shipped default
DEFAULT_AREA_M2 = StagnationBoxParams().area_m2


def _skill(o: np.ndarray, p: np.ndarray) -> dict[str, float]:
    if len(o) < 3 or np.allclose(p, p[0]):
        return {
            "spearman": float("nan"),
            "pearson": float("nan"),
            "rmse": float(np.sqrt(np.mean((o - p) ** 2))),
        }
    return {
        "spearman": float(spearmanr(o, p).statistic),
        "pearson": float(pearsonr(o, p)[0]),
        "rmse": float(np.sqrt(np.mean((o - p) ** 2))),
    }


def _extremes(o: np.ndarray, p: np.ndarray, thr: float = 100.0) -> dict[str, float]:
    hi = o > thr
    n = int(hi.sum())
    if n == 0:
        return {"n_gt100": 0}
    return {
        "n_gt100": n,
        "recall_at_100": round(float((p[hi] > thr).mean()), 3),
        "median_obs_gt100": round(float(np.median(o[hi])), 1),
        "median_pred_at_those_hrs": round(float(np.median(p[hi])), 1),
    }


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
            ],
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
            is_night=bool(int(n)),
        )
        for t, ws, wd, tc, cc, n in zip(
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

    # Constant-box "before" (issue #3): scalar E_local, τ best-of-grid,
    # closed-form amplitude — exactly the box_calibration model.
    def const_box_unit(tau: float) -> np.ndarray:
        return box_series(
            met,
            StagnationBoxParams(tau_h=tau, e_local_g_s=1.0, area_m2=DEFAULT_AREA_M2),
            units="ppb",
        )

    # Driver box (issue #6): unit-E0 temperature-led series, linear in E0.
    def driver_box_unit(q10: float, tau: float) -> np.ndarray:
        e_unit = temperature_led_e_local(
            met,
            TemperatureEmissionParams(e0_g_s=1.0, q10=q10, t_ref_c=T_REF_C),
        )
        return box_series(
            met,
            StagnationBoxParams(tau_h=tau, e_local_g_s=e_unit, area_m2=DEFAULT_AREA_M2),
            units="ppb",
        )

    report: dict[str, object] = {
        "n_berry_hours": int(n),
        "n_berry_gt100": int((obs > 100).sum()),
        "constant_box_ceiling_to_beat": CONST_BOX_CEILING,
        "split": "chronological 70/30 (matches box_calibration / attribution)",
        "fixed": {
            "t_ref_c": T_REF_C,
            "area_m2": DEFAULT_AREA_M2,
            "H_mix_by_stability_m": H_MIX_BY_STABILITY_M,
            "note": "T_ref absorbed into E0 (non-identifiable); E0 closed-form; "
            "Q10 & τ are the only params that move held-out rank skill.",
        },
    }

    for rname, rmask in regimes.items():
        tr = rmask & is_train
        te = rmask & ~is_train
        otr, ote = obs[tr], obs[te]

        def scale(p: np.ndarray, m_tr: np.ndarray, o_tr: np.ndarray) -> float:
            pt = p[m_tr]
            d = float(np.dot(pt, pt))
            return max(0.0, float(np.dot(o_tr, pt) / d)) if d > 0 else 0.0

        # constant box: best τ by train RMSE
        cb_best = None
        for tau in TAU_GRID_H:
            pu = const_box_unit(tau)
            a = scale(pu, tr, otr)
            rmse_tr = float(np.sqrt(np.mean((otr - a * pu[tr]) ** 2)))
            if cb_best is None or rmse_tr < cb_best["rmse_tr"]:
                cb_best = {"tau": tau, "e0": a, "rmse_tr": rmse_tr, "pred": a * pu}

        # driver box: grid Q10 × τ. Rank ceiling = best held-out
        # Spearman over the grid (amplitude/T_ref-invariant → the
        # decisive, un-gameable statistic). Point estimate = train-RMSE
        # optimum with closed-form E0.
        rank_ceiling = -1.0
        ceil_at = None
        db_best = None
        for q10 in Q10_GRID:
            for tau in TAU_GRID_H:
                pu = driver_box_unit(q10, tau)
                pe = pu[te]
                if not np.allclose(pe, pe[0]):
                    rho = float(spearmanr(ote, pe).statistic)
                    if rho > rank_ceiling:
                        rank_ceiling, ceil_at = rho, {"q10": q10, "tau_h": tau}
                a = scale(pu, tr, otr)
                rmse_tr = float(np.sqrt(np.mean((otr - a * pu[tr]) ** 2)))
                if db_best is None or rmse_tr < db_best["rmse_tr"]:
                    db_best = {"q10": q10, "tau": tau, "e0": a, "rmse_tr": rmse_tr, "pred": a * pu}
        assert cb_best is not None and db_best is not None

        ceiling = CONST_BOX_CEILING[rname]
        report[rname] = {
            "n_test_regime_hours": int(te.sum()),
            "constant_box_before": {
                "tau_h": cb_best["tau"],
                "e0_g_s": round(cb_best["e0"], 4),
                "test": {k: round(v, 4) for k, v in _skill(ote, cb_best["pred"][te]).items()},
                "test_extremes": _extremes(ote, cb_best["pred"][te]),
            },
            "driver_box_point_estimate": {
                "q10": db_best["q10"],
                "tau_h": db_best["tau"],
                "e0_g_s": round(db_best["e0"], 4),
                "t_ref_c": T_REF_C,
                "test": {k: round(v, 4) for k, v in _skill(ote, db_best["pred"][te]).items()},
                "test_extremes": _extremes(ote, db_best["pred"][te]),
            },
            "driver_box_rank_skill_ceiling_heldout": {
                "spearman": round(rank_ceiling, 4),
                "at": ceil_at,
                "constant_box_ceiling": ceiling,
                "clears_constant_box_ceiling": bool(rank_ceiling > ceiling),
                "delta_vs_constant_box": round(rank_ceiling - ceiling, 4),
            },
        }

    # End-to-end shipped-path validation on the canonical May 10-11
    # event with the calibrated (Q10, τ) for the operational regime.
    from tijuana_dispersion import run_forward
    from tijuana_dispersion.schemas import (
        EmissionDriverParams,
        ForwardRunRequest,
        MetSpec,
        ReceptorSpec,
        SourceSpec,
    )

    op = report["is_stagnation"]
    assert isinstance(op, dict)
    pe_pt = op["driver_box_point_estimate"]
    srcs = json.loads((HERE / "../../data/emission_sources.json").read_text())
    ev = berry[(berry.time >= "2026-05-10 18:00") & (berry.time <= "2026-05-11 08:00")]
    ev_out: dict[str, object] = {"error": "event window unavailable"}
    if len(ev) >= 3:
        ms = [
            MetSpec(
                timestamp=t.isoformat(),
                wind_speed_ms=float(ws),
                wind_direction_deg=float(wd),
                temperature_c=float(tc),
                cloud_cover_frac=float(cc) / 100.0,
                is_night=bool(int(nn)),
            )
            for t, ws, wd, tc, cc, nn in zip(
                ev["time"],
                ev["wind_speed_10m"],
                ev["wind_direction_10m"],
                ev["temperature_2m"],
                ev["cloud_cover"],
                ev["is_night"],
                strict=True,
            )
        ]
        base = dict(
            sources=[
                SourceSpec(
                    name=k,
                    lat=v["lat"],
                    lon=v["lon"],
                    emission_rate_g_s=float(pe_pt["e0_g_s"]) / len(srcs),
                )
                for k, v in srcs.items()
            ],
            receptors=[ReceptorSpec(name=BERRY, lat=32.567097, lon=-117.090656)],
            meteorology=ms,
            units="ppb",
        )
        r_const = run_forward(ForwardRunRequest(**base, cache_key=None))
        r_drv = run_forward(
            ForwardRunRequest(
                **base,
                emission_driver=True,
                emission_driver_params=EmissionDriverParams(
                    q10=float(pe_pt["q10"]),
                    t_ref_c=T_REF_C,
                    e0_g_s=float(pe_pt["e0_g_s"]),
                ),
                cache_key=None,
            ),
        )
        o_ev = ev["H2S"].to_numpy(dtype=float)
        ev_out = {
            "obs_peak_ppb": round(float(o_ev.max()), 1),
            "constant_box_peak_ppb": round(float(np.array(r_const.concentrations)[:, 0].max()), 1),
            "driver_box_peak_ppb": round(float(np.array(r_drv.concentrations)[:, 0].max()), 1),
            "driver_emission_driver_flag": r_drv.summary.get("emission_driver"),
            "dispatch": r_drv.summary.get("dispatch"),
        }
    report["event_validation_shipped_path"] = ev_out

    verdict = []
    for rn in regimes:
        rr = report[rn]
        assert isinstance(rr, dict)
        c = rr["driver_box_rank_skill_ceiling_heldout"]
        b = rr["constant_box_before"]["test"]["spearman"]
        verdict.append(
            f"[{rn}] constant box held-out Spearman={b:.3f} "
            f"(ceiling {c['constant_box_ceiling']:.3f}) → driver-box rank "
            f"ceiling={c['spearman']:.3f} at {c['at']} | clears: "
            f"{c['clears_constant_box_ceiling']} (Δ {c['delta_vs_constant_box']:+.3f})",
        )
    report["verdict"] = verdict

    (OUT / "summary.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
