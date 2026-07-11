"""Score candidate calibration/validation windows for the multi-window campaign.

Slides a 3-day window over the NESTOR record and scores each on what the
pooled fit needs (docs/calibration_status.md 2026-07-11 entries):

- obs coverage per receptor (H2S hours present / window hours)
- NESTOR H2S signal (mean; the calm-night stratum is the target)
- calm-night hours (is_night & wind < 2.5 m/s — the stagnation-box regime)
- border-flow contrast within the window (identifies a_flow; note the
  feed is frozen at 2.10 m3/s from Jan 2026 — zero contrast there)
- met completeness (wind speed/direction present)

Usage:
    uv run python nrp/scripts/select_windows.py [--days 3] [--top 15]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nrp import sobol

FLOW_COL = "Flow (m^3/s)--Border"


def score_windows(days: int = 3) -> pd.DataFrame:
    df = pd.read_parquet(sobol.DEFAULT_PARQUET)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")

    nestor = df[df.site_name == "NESTOR - BES"].set_index("time").sort_index()
    others = {
        name: df[df.site_name == name].set_index("time")["H2S"] for name in sobol.RECEPTOR_NAMES
    }

    start = nestor.index.min().normalize()
    end = nestor.index.max().normalize() - pd.Timedelta(days=days)
    rows = []
    day = pd.Timedelta(days=1)
    w = pd.Timedelta(days=days)
    t0 = start
    while t0 <= end:
        t1 = t0 + w
        n = nestor[(nestor.index >= t0) & (nestor.index < t1)]
        if len(n) < days * 20:  # window mostly missing
            t0 += day
            continue
        calm = (n["day_night"] == "night") & (n["wind_speed_10m"] < 2.5)
        flow = n[FLOW_COL].dropna()
        cov = {
            name: float(s[(s.index >= t0) & (s.index < t1)].notna().mean())
            for name, s in others.items()
        }
        rows.append(
            {
                "start": t0.strftime("%Y-%m-%d"),
                "end": t1.strftime("%Y-%m-%d"),
                "nestor_h2s_mean": float(n["H2S"].mean()),
                "nestor_calm_night_h2s": float(n.loc[calm, "H2S"].mean()),
                "calm_night_hours": int(calm.sum()),
                "flow_min": float(flow.min()) if len(flow) else np.nan,
                "flow_max": float(flow.max()) if len(flow) else np.nan,
                "flow_contrast": float(flow.max() - flow.min()) if len(flow) else np.nan,
                "met_complete": float(n["wind_speed_10m"].notna().mean()),
                **{f"cov_{k.split()[0]}": v for k, v in cov.items()},
            }
        )
        t0 += day
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    scored = score_windows(days=args.days)
    usable = scored[
        (scored.met_complete > 0.95) & (scored.cov_NESTOR > 0.8) & (scored.calm_night_hours >= 8)
    ]
    pd.set_option("display.width", 200)

    print(f"== top {args.top} by NESTOR calm-night signal (any flow) ==")
    print(
        usable.nlargest(args.top, "nestor_calm_night_h2s").to_string(
            index=False, float_format=lambda x: f"{x:.2f}"
        )
    )
    print(f"\n== top {args.top} by flow contrast (identifies a_flow) ==")
    print(
        usable.nlargest(args.top, "flow_contrast").to_string(
            index=False, float_format=lambda x: f"{x:.2f}"
        )
    )


if __name__ == "__main__":
    main()
