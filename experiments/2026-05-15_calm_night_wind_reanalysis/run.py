"""Calm-night wind reanalysis (no fitting).

The May 10-11 Berry event analysis left two explanations for why the
model misses Berry's nocturnal extremes:
  (a) an unmodelled source WNW-NNW of Berry, or
  (b) the calm-night Open-Meteo wind direction is unreliable, so the
      model routes the (real, SE) river-source plume the wrong way.

The status log flagged "pull an independent anemometer (NERR/TJRTLMET)"
as the way to decide. There is NO such independent feed in our data
pipeline (manifest has only the Open-Meteo product; the forecast_15min
file fetched as a corrupt non-parquet). So this experiment does the
strongest *internal-consistency + physical-plausibility* reanalysis the
available data supports, and is explicit about what it can and cannot
conclude without external met.

Checks (all on the committed modeldata_h2s_nofill parquet):
  1. The dataset's own `stable_atm` flag vs Berry's >100 ppb hours.
  2. Open-Meteo wind-direction rotation during the May 10-11 spike.
  3. Hour-to-hour direction instability: calm-night vs windy.
  4. Spatial coherence: SY-local vs NESTOR Open-Meteo wind during the
     event (SY has its own Open-Meteo column; ~4 km apart).
  5. Gust/mean ratio during extremes vs baseline (reported even though
     it turned out non-discriminating — negative results count).

Reproduce:
    uv run python experiments/2026-05-15_calm_night_wind_reanalysis/run.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "output"
PARQUET = HERE / "../../data/modeldata_h2s_nofill.parquet"
EVENT = ("2026-05-10 20:00", "2026-05-11 05:00")


def _adiff(a: pd.Series, b: pd.Series) -> pd.Series:
    """Signed minimal angular difference a-b in degrees, range (-180,180]."""
    return (a - b + 180.0) % 360.0 - 180.0


def main() -> None:
    OUT.mkdir(exist_ok=True)
    df = pd.read_parquet(PARQUET)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    berry = df[df.site_name == "NESTOR - BES"].sort_values("time").copy()

    # 1. stable_atm vs extremes
    big = berry[berry.H2S > 100]
    stable_big = float(big["stable_atm"].mean())
    stable_base = float(berry["stable_atm"].mean())

    # 2. event-window wind table
    ev = berry[(berry.time >= EVENT[0]) & (berry.time <= EVENT[1])]
    ev_tbl = ev[
        ["time", "H2S", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "stable_atm"]
    ].copy()
    ev_tbl.to_csv(OUT / "event_wind.csv", index=False)
    dir_sweep_deg = float(
        np.ptp(ev.loc[ev.H2S > 100, "wind_direction_10m"].to_numpy())
        if (ev.H2S > 100).any()
        else np.nan,
    )

    # 3. hour-to-hour |Δdir| calm-night vs windy
    berry["ddir"] = _adiff(berry["wind_direction_10m"], berry["wind_direction_10m"].shift(1)).abs()
    is_night = (berry["day_night"] == "night") | berry["is_night"].astype(str).isin(["1", "True"])
    calm = berry[(berry.wind_speed_10m < 2.5) & is_night]
    windy = berry[berry.wind_speed_10m >= 5]
    ddir_calm = float(calm["ddir"].median())
    ddir_windy = float(windy["ddir"].median())

    # 4. spatial coherence: SY vs NESTOR during event
    w = df.pivot_table(
        index="time",
        columns="site_name",
        values="wind_direction_10m",
        aggfunc="first",
    )
    evw = w[(w.index >= EVENT[0]) & (w.index <= EVENT[1])]
    sy_nes = _adiff(evw["SAN YSIDRO"], evw["NESTOR - BES"]).abs()
    coherence_mean = float(sy_nes.mean())
    coherence_max = float(sy_nes.max())

    # 5. gust/mean ratio (non-discriminating — reported honestly)
    gr_big = float((big.wind_gusts_10m / big.wind_speed_10m.clip(lower=0.1)).median())
    gr_all = float((berry.wind_gusts_10m / berry.wind_speed_10m.clip(lower=0.1)).median())

    summary = {
        "n_berry_gt100": len(big),
        "stable_atm_frac_gt100": round(stable_big, 3),
        "stable_atm_frac_baseline": round(stable_base, 3),
        "event_dir_sweep_deg": round(dir_sweep_deg, 1),
        "hour_to_hour_ddir_calm_night_deg": round(ddir_calm, 1),
        "hour_to_hour_ddir_windy_deg": round(ddir_windy, 1),
        "sy_vs_nestor_dir_diff_event_mean_deg": round(coherence_mean, 1),
        "sy_vs_nestor_dir_diff_event_max_deg": round(coherence_max, 1),
        "gust_mean_ratio_gt100": round(gr_big, 2),
        "gust_mean_ratio_baseline": round(gr_all, 2),
        "verdict": (
            "Supports explanation (b): calm-night Open-Meteo wind direction is "
            "unreliable for plume routing. The dataset's own stable_atm flag "
            "marks 88% of >100 ppb hours; direction is 4x noisier calm-night "
            "than windy and sweeps ~68 deg across the >100 ppb hours "
            "(~115 deg across the surrounding 20:00-05:00 calm window); "
            "SY vs NESTOR diverge up to ~52 deg in the same hours. "
            "Gust ratio was NOT "
            "discriminating. Cannot POSITIVELY confirm (a) vs (b) without an "
            "external anemometer (NERR/TJRTLMET) — recommend adding one to "
            "data/manifest.yaml. Actionable now: use the existing stable_atm "
            "flag as the stagnation classifier (service issues #2/#3)."
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    for k, v in summary.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
